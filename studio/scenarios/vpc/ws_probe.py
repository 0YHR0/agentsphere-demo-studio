"""Single-connection RFC6455 echo check; runs inside the sandbox with stdlib."""
import base64
import hashlib
import json
import os
import socket
import select
import ssl
import struct
import sys
import time
from urllib.parse import urlsplit


def probe(url, duration, idle):
    u = urlsplit(url)
    start = time.perf_counter()
    result = dict(status='failed', url=url, duration_target_s=duration, idle_target_s=idle,
                  open_count=0, reconnects=0, echoes=[], errors=[])
    sock = stream = None
    try:
        port = u.port or (443 if u.scheme == 'wss' else 80)
        sock = socket.create_connection((u.hostname, port), timeout=8)
        if u.scheme == 'wss': sock = ssl.create_default_context().wrap_socket(sock, server_hostname=u.hostname)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (f'GET {u.path or "/"} HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: websocket\r\n'
                   f'Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n')
        sock.sendall(request.encode())
        stream = sock.makefile('rb', buffering=0)
        status = stream.readline().decode().strip()
        headers = {}
        while True:
            line = stream.readline()
            if line == b'\r\n': break
            if not line: raise RuntimeError('Incomplete upgrade response')
            k, v = line.decode().split(':', 1); headers[k.lower()] = v.strip()
        expected = base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        if status.split()[1] != '101' or headers.get('sec-websocket-accept') != expected:
            raise RuntimeError('Invalid WebSocket upgrade: ' + status)
        result.update(handshake_status=101, open_count=1)
        def exact(n):
            data = bytearray()
            while len(data) < n:
                block = stream.read(n-len(data))
                if not block: raise RuntimeError('WebSocket closed before echo')
                data.extend(block)
            return bytes(data)
        def send(op, payload):
            mask = os.urandom(4)
            n = len(payload)
            prefix = bytes([0x80|op, 0x80|n]) if n < 126 else bytes([0x80|op, 0x80|126])+struct.pack('>H', n)
            sock.sendall(prefix+mask+bytes(c^mask[i%4] for i,c in enumerate(payload)))
        def echo(payload):
            sent = time.perf_counter(); send(1, payload)
            fragments = bytearray()
            while True:
                head = exact(2); op = head[0]&15; n = head[1]&127
                if head[1]&128: raise RuntimeError('Server frame must not be masked')
                if n == 126: n = struct.unpack('>H', exact(2))[0]
                elif n == 127: n = struct.unpack('>Q', exact(8))[0]
                if n > 1024*1024: raise RuntimeError('Unexpected oversized frame')
                data = exact(n)
                if op == 9: send(10, data); continue
                if op == 10: continue
                if op == 8: raise RuntimeError('Server sent close')
                if op not in (0, 1): raise RuntimeError('Unexpected frame opcode')
                fragments.extend(data)
                if head[0]&128:
                    if bytes(fragments) != payload: raise RuntimeError('Echo content mismatch')
                    result['echoes'].append({'elapsed_s':time.perf_counter()-start, 'rtt_ms':(time.perf_counter()-sent)*1000})
                    return
        sock.settimeout(10)
        echo(b'agentsphere-vpc-before-idle')
        # No application messages during this interval. A following echo must work on this socket.
        result['idle_started_s'] = time.perf_counter()-start
        until = time.perf_counter()+idle
        while time.perf_counter() < until:
            pending = sock.pending() if isinstance(sock, ssl.SSLSocket) else 0
            if not pending and not select.select([sock], [], [], min(1, max(0, until-time.perf_counter())))[0]:
                continue
            head = exact(2); op = head[0]&15; n = head[1]&127
            if head[1]&128 or n > 125 or op not in (8,9,10):
                raise RuntimeError('Unexpected frame during echo-service idle interval')
            data = exact(n)
            if op == 8: raise RuntimeError('Server closed during idle interval')
            if op == 9: send(10, data)
        echo(b'agentsphere-vpc-after-idle')
        result['idle_completed_s'] = time.perf_counter()-start
        while time.perf_counter()-start < duration:
            time.sleep(min(5, max(0, duration-(time.perf_counter()-start))))
            echo(('agentsphere-vpc-'+str(len(result['echoes']))).encode())
        result['status'] = 'passed'
        send(8, struct.pack('>H',1000))
    except Exception as exc:
        result['status'] = 'failed'
        result['errors'].append(type(exc).__name__+': '+str(exc))
    finally:
        if stream: stream.close()
        if sock: sock.close()
        result['elapsed_s'] = time.perf_counter()-start
    return result


if __name__ == '__main__':
    answer = probe(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
    print(json.dumps(answer))
    sys.exit(0 if answer['status'] == 'passed' else 1)
