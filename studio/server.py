import argparse
import hmac
import inspect
import json
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .catalog import CATALOG, SCENARIO_FIELDS
from .config import Config, ROOT
from .engine import Engine
from .core.registry import get_registry


def handler_for(engine, csrf):
    registry = get_registry()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def valid_host(self):
            return self.headers.get('Host') in (
                f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def send_json(self, value, status=200):
            data = json.dumps(engine.safe(value), ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.valid_host():
                return self.send_json({'error': 'Invalid Host'}, 403)
            path = urlsplit(self.path).path
            if path == '/api/state':
                return self.send_json({**engine.snapshot(), 'csrf': csrf})
            if path == '/api/catalog':
                return self.send_json(list(CATALOG.values()))
            if path == '/api/scenarios':
                return self.send_json(registry.scenarios())
            if path == '/api/packages':
                return self.send_json([p.public() for p in registry.packages.values()])
            if path == '/api/report':
                return self.send_json(engine.export_report())
            if path == '/api/report.md':
                from .core.reporting import markdown_report
                data = markdown_report(engine.export_report()).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/markdown; charset=utf-8')
                self.send_header('Content-Disposition', 'attachment; filename="agentsphere-run-report.md"')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path.startswith('/api/case/'):
                case = path.rsplit('/', 1)[-1]
                if case not in CATALOG:
                    return self.send_json({'error': '未知演示能力'}, 404)
                code = registry.package_for(case).source(case)
                return self.send_json({'case': CATALOG[case], 'code': code, 'plan': engine.plan(case)})
            assets = {'/': ('web/index.html', 'text/html'), '/app.js': ('web/app.js', 'text/javascript'),
                      '/order-reports.js': ('web/order-reports.js', 'text/javascript'),
                      '/style.css': ('web/style.css', 'text/css'),
                      '/order-reports.css': ('web/order-reports.css', 'text/css'),
                      '/README.md': ('README.md', 'text/plain'),
                      '/sdk-versions.json': ('sdk-versions.json', 'application/json')}
            if path not in assets:
                return self.send_json({'error': 'Not found'}, 404)
            name, mime = assets[path]
            data = (ROOT / name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy',
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if not self.valid_host():
                return self.send_json({'error': 'Invalid Host'}, 403)
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host', ''):
                return self.send_json({'error': 'Invalid origin'}, 403)
            if not hmac.compare_digest(self.headers.get('X-Studio-CSRF', ''), csrf):
                return self.send_json({'error': '请刷新页面后重试'}, 403)
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.send_json({'error': 'JSON required'}, 415)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 65536:
                    raise ValueError('请求大小无效')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('请求体必须为 JSON 对象')
                path = urlsplit(self.path).path
                if path == '/api/config':
                    with engine.lock:
                        if engine.job:
                            raise ValueError('执行中不能修改配置')
                        unresolved = any(not r.get('deleted') for k in ('sandboxes', 'templates')
                                         for r in engine.state[k])
                        identity = ('api_url', 'api_key', 'gateway_id', 'gateway_url')
                        if unresolved and any(data.get(k) and data[k] != engine.config.data[k]
                                              for k in identity):
                            raise ValueError('请先清理本工具资源，再切换账号或 Gateway')
                        return self.send_json(engine.config.save(data))
                if path == '/api/scenario-config':
                    with engine.lock:
                        if engine.job:
                            raise ValueError('执行中不能修改场景配置')
                        case, values = data.get('case'), data.get('values')
                        allowed = SCENARIO_FIELDS.get(case)
                        if allowed is None or not isinstance(values, dict) or set(values) - allowed:
                            raise ValueError('无效的场景配置字段')
                        package = registry.package_for(case)
                        if package.validate_config:
                            package.validate_config({**engine.config.data, **values}, case)
                        return self.send_json(engine.config.save(values))
                if path == '/api/action':
                    job = engine.start(data.get('case'), data.get('mode', 'run'), data.get('execution'))
                    return self.send_json({'job_id': job}, 202)
                if path == '/api/stop':
                    engine.stop.set()
                    return self.send_json({'stop_requested': True,
                                           'note': '已发送的云端 Build 不会被撤回，资源会保留。'})
                return self.send_json({'error': 'Not found'}, 404)
            except (ValueError, TypeError, KeyError) as exc:
                return self.send_json({'error': str(exc)}, 400)
    return Handler


def main():
    parser = argparse.ArgumentParser(description='AgentSphere Demo Studio')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--data-dir', default=str(ROOT / '.local'))
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    config = Config(Path(args.data_dir))
    engine = Engine(config)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(engine, secrets.token_urlsafe(32)))
    url = f'http://127.0.0.1:{args.port}/'
    print('AgentSphere Demo Studio: ' + url, flush=True)
    print('Local configuration and resource ledger: ' + str(config.directory), flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        engine.stop.set()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
