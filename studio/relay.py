"""Local-only provider credential relay over the already-authenticated SDK.

No public tunnel or model-provider credential is installed inside a sandbox.
"""
import json
import re
import threading
from pathlib import Path

import httpx


class ModelRelay:
    def __init__(self, driver, sandbox_id, directory, user, config, log):
        self.driver, self.sid, self.directory = driver, sandbox_id, directory
        self.user, self.config, self.log = user, config, log
        self.stop = threading.Event()
        self.process = None
        self.thread = None
        self.calls = 0
        self.error = None

    def start(self):
        import shlex
        source = Path(__file__).with_name('remote_relay.py').read_text(encoding='utf-8')
        self.driver.write(self.sid, self.directory + '/model_relay.py', source, user=self.user)
        command = ('python3 ' + shlex.quote(self.directory + '/model_relay.py') + ' ' +
                   shlex.quote(self.directory) + ' ' + shlex.quote(self.config['model_id']))
        self.process = self.driver.background(self.sid, command, user=self.user)
        for _ in range(30):
            if self.stop.wait(.3):
                raise RuntimeError('模型中转已停止')
            try:
                ready = json.loads(self.driver.read(self.sid, self.directory + '/ready.json', user=self.user))
                self.thread = threading.Thread(target=self.serve, daemon=True)
                self.thread.start()
                self.log('模型 Key 留在本机；仅通过 SDK 文件交换模型请求和结果。')
                return 'http://127.0.0.1:' + str(int(ready['port'])) + '/v1'
            except (FileNotFoundError, RuntimeError):
                continue
            except Exception as exc:
                # SDK file-not-found errors differ by version; retry only during startup.
                if 'not found' not in str(exc).lower() and 'no such file' not in str(exc).lower():
                    raise
        raise RuntimeError('沙箱内模型中转启动失败；检查 python3 和用户目录权限')

    def serve(self):
        seen = set()
        try:
            with httpx.Client(timeout=120, follow_redirects=False, trust_env=False) as client:
                while not self.stop.is_set():
                    files = self.driver.list_files(self.sid, self.directory + '/requests', user=self.user)
                    for name in files:
                        if not re.fullmatch(r'[0-9a-f]{32}\.json', name) or name in seen:
                            continue
                        if self.calls >= 12:
                            raise RuntimeError('演示模型调用已达到 12 次上限')
                        payload = json.loads(self.driver.read(self.sid,
                            self.directory + '/requests/' + name, user=self.user))
                        payload['stream'] = False
                        payload.pop('stream_options', None)
                        payload['model'] = self.config['model_id']
                        payload['max_tokens'] = min(int(payload.get('max_tokens') or 4096), 4096)
                        if 'api.deepseek.com' in self.config['model_base_url']:
                            payload['thinking'] = {'type': 'disabled'}
                        self.calls += 1
                        self.log('本机正在调用模型，第 ' + str(self.calls) + ' 次。')
                        try:
                            response = client.post(self.config['model_base_url'].rstrip('/') + '/chat/completions',
                                headers={'Authorization': 'Bearer ' + self.config['model_api_key']}, json=payload)
                            try:
                                body = response.json()
                            except ValueError:
                                body = {'error': {'message': '模型服务返回非 JSON 响应'}}
                            envelope = {'status': response.status_code, 'body': body}
                        except httpx.HTTPError as exc:
                            envelope = {'status': 502, 'body': {'error': {'message': type(exc).__name__}}}
                        # Even a provider echo must not carry the real key to the sandbox.
                        encoded = json.dumps(envelope).replace(self.config['model_api_key'], '[REDACTED]')
                        self.driver.write(self.sid, self.directory + '/responses/' + name,
                                          encoded, user=self.user)
                        seen.add(name)
                    self.stop.wait(.3)
        except Exception as exc:
            self.error = type(exc).__name__ + ': ' + str(exc)
            self.log('本机模型中转失败：' + self.error)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=130)
        if self.process:
            try:
                self.process.kill()
            except Exception:
                pass
