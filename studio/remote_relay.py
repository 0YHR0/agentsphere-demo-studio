"""Loopback OpenAI-compatible endpoint for a sandbox. Contains NO provider key.

Requests/responses are exchanged through E2B files by the local workstation.
The real provider HTTPS request is made only by the workstation's relay module.
"""
import json
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    directory = Path(sys.argv[1])
    model = sys.argv[2]
    for name in ('requests', 'responses'):
        (directory / name).mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.rstrip('/') == '/v1/models':
                return self.reply(200, {'object': 'list', 'data': [{'id': model, 'object': 'model'}]})
            self.reply(404, {'error': 'not found'})

        def do_POST(self):
            if self.path != '/v1/chat/completions':
                return self.reply(404, {'error': 'not found'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 2_000_000:
                    return self.reply(413, {'error': 'request too large'})
                request = json.loads(self.rfile.read(size))
                identity = uuid.uuid4().hex
                dest = directory / 'requests' / (identity + '.json')
                temporary = dest.with_suffix('.tmp')
                temporary.write_text(json.dumps(request), encoding='utf-8')
                os.replace(temporary, dest)
                answer = directory / 'responses' / (identity + '.json')
                deadline = time.monotonic() + 150
                while not answer.exists():
                    if time.monotonic() > deadline:
                        return self.reply(504, {'error': 'local model relay timed out'})
                    time.sleep(.15)
                envelope = json.loads(answer.read_text(encoding='utf-8'))
                body, status = envelope['body'], envelope['status']
                if not request.get('stream') or status != 200:
                    return self.reply(status, body)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                for chunk in chunks(body):
                    self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n')
                self.wfile.flush()
            except Exception as exc:
                self.reply(500, {'error': type(exc).__name__})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    (directory / 'ready.json').write_text(json.dumps({'port': server.server_port, 'pid': os.getpid()}))
    server.serve_forever()


def chunks(body):
    """Turn a complete provider response into valid OpenAI SSE chunks."""
    common = {'id': body.get('id', 'local-relay'), 'object': 'chat.completion.chunk',
              'created': body.get('created', int(time.time())), 'model': body.get('model', '')}
    for choice in body.get('choices', []):
        message = dict(choice.get('message', {}))
        if message.get('tool_calls'):
            message['tool_calls'] = [{**tool, 'index': index}
                                      for index, tool in enumerate(message['tool_calls'])]
        yield {**common, 'choices': [{'index': choice.get('index', 0), 'delta': message,
                                     'finish_reason': None}]}
        yield {**common, 'choices': [{'index': choice.get('index', 0), 'delta': {},
                                     'finish_reason': choice.get('finish_reason', 'stop')}],
               **({'usage': body['usage']} if 'usage' in body else {})}


if __name__ == '__main__':
    main()
