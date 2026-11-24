"""Dependency-free VPC test service: HTTP /health and WebSocket /ws, port 8080."""
import argparse
import base64
import hashlib
import json
import socket
import struct
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LIMIT=1024*1024

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def do_GET(self):
        if self.path.split('?',1)[0]=='/ws' and self.headers.get('Upgrade','').lower()=='websocket':
            return self.websocket()
        body=json.dumps({'ok':True,'service':'agentsphere-vpc-demo','hostname':socket.gethostname(),'time':time.time(),'path':self.path}).encode()
        self.send_response(200 if self.path.split('?',1)[0] in ('/','/health') else 404)
        self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def exact(self,n):
        data=self.rfile.read(n)
        if len(data)!=n:raise EOFError()
        return data
    def frame(self,opcode,payload=b''):
        header=bytes([0x80|opcode])
        if len(payload)<126:header+=bytes([len(payload)])
        elif len(payload)<=65535:header+=bytes([126])+struct.pack('!H',len(payload))
        else:header+=bytes([127])+struct.pack('!Q',len(payload))
        self.wfile.write(header+payload);self.wfile.flush()
    def websocket(self):
        key=self.headers.get('Sec-WebSocket-Key','')
        try:valid=len(base64.b64decode(key,validate=True))==16
        except Exception:valid=False
        if not valid or self.headers.get('Sec-WebSocket-Version')!='13':
            self.send_error(400,'Expected RFC6455 handshake');return
        accept=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        self.send_response(101);self.send_header('Upgrade','websocket');self.send_header('Connection','Upgrade');self.send_header('Sec-WebSocket-Accept',accept);self.end_headers();self.wfile.flush()
        self.close_connection=True;fragments=bytearray();fragment_opcode=None
        try:
            while True:
                a,b=self.exact(2);fin=bool(a&0x80);opcode=a&15;masked=bool(b&0x80);length=b&127
                if a&0x70 or not masked:self.frame(8,struct.pack('!H',1002));return
                if length==126:length=struct.unpack('!H',self.exact(2))[0]
                elif length==127:length=struct.unpack('!Q',self.exact(8))[0]
                if length>LIMIT or len(fragments)+length>LIMIT:self.frame(8,struct.pack('!H',1009));return
                if opcode>=8 and (not fin or length>125):self.frame(8,struct.pack('!H',1002));return
                mask=self.exact(4);payload=bytes(x^mask[i%4] for i,x in enumerate(self.exact(length)))
                if opcode==8:self.frame(8,payload);return
                if opcode==9:self.frame(10,payload);continue
                if opcode==10:continue
                if opcode in (1,2):
                    if fragment_opcode is not None:self.frame(8,struct.pack('!H',1002));return
                    if fin:self.frame(opcode,payload)
                    else:fragment_opcode=opcode;fragments.extend(payload)
                elif opcode==0 and fragment_opcode is not None:
                    fragments.extend(payload)
                    if fin:self.frame(fragment_opcode,bytes(fragments));fragments.clear();fragment_opcode=None
                else:self.frame(8,struct.pack('!H',1002));return
        except (EOFError,BrokenPipeError,ConnectionResetError,TimeoutError):return

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--bind',default='0.0.0.0');parser.add_argument('--port',type=int,default=8080);args=parser.parse_args()
    server=ThreadingHTTPServer((args.bind,args.port),Handler);server.daemon_threads=True
    print(json.dumps({'listen':f'{args.bind}:{args.port}','http':'/health','websocket':'/ws'}),flush=True)
    server.serve_forever()
