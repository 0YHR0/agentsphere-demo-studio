import os,json,time,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
D=Path('/tmp/agentsphere-native-health');D.mkdir(exist_ok=True)
boot=uuid.uuid4().hex;pid=os.getpid()
(D/'unhealthy').unlink(missing_ok=True)
record={'boot_id':boot,'pid':pid,'at':time.time()}
with (D/'starts.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
(D/'current.json').write_text(json.dumps(record))
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  health=self.path.split('?')[0] in ('/health','/healthz')
  bad=(D/'unhealthy').exists()
  status=503 if health and bad else 200
  event={'at':time.time(),'path':self.path,'status':status,'peer':self.client_address[0],'user_agent':self.headers.get('User-Agent'),'pid':pid,'boot_id':boot}
  with (D/'requests.jsonl').open('a') as f:f.write(json.dumps(event)+'\n')
  body=json.dumps({'healthy':not bad,'pid':pid,'boot_id':boot,'status':status}).encode()
  self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
ThreadingHTTPServer(('0.0.0.0',18080),Handler).serve_forever()
