"""Linux sandbox benchmark launcher. All expected reports/reward stay on host."""
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile
import time

from csv_data import PROFILES,VERSION,write_csv


def benchmark(program,data,action,group,timeout=10):
    def limits():
        resource.setrlimit(resource.RLIMIT_CPU,(11,11))
        resource.setrlimit(resource.RLIMIT_AS,(256*1024**2,256*1024**2))
        resource.setrlimit(resource.RLIMIT_FSIZE,(4*1024**2,4*1024**2))
        resource.setrlimit(resource.RLIMIT_NOFILE,(32,32))
        resource.setrlimit(resource.RLIMIT_NPROC,(32,32))
    with tempfile.TemporaryDirectory(prefix='order-strategy-') as temporary:
        with (Path(temporary)/'out').open('w+b') as out,(Path(temporary)/'err').open('w+b') as err:
            start=time.perf_counter()
            child=subprocess.Popen([sys.executable,'-I',str(program),str(data),action,group],stdout=out,stderr=err,
                cwd=temporary,start_new_session=True,preexec_fn=limits,env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8'})
            timed_out=False;usage=None
            try:
                while True:
                    pid,status,usage=os.wait4(child.pid,os.WNOHANG)
                    if pid:break
                    if time.perf_counter()-start>timeout:
                        timed_out=True;os.killpg(child.pid,signal.SIGKILL);pid,status,usage=os.wait4(child.pid,0);break
                    time.sleep(.002)
                child.returncode=os.waitstatus_to_exitcode(status)
            finally:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                if child.returncode is None:child.wait()
            elapsed=time.perf_counter()-start
            out.seek(0);stdout=out.read(2*1024**2).decode('utf-8','replace')
            err.seek(0);stderr=err.read(4096).decode('utf-8','replace')
    return dict(returncode=child.returncode,timed_out=timed_out,stdout=stdout,stderr=stderr,
        wall_s=elapsed,cpu_s=usage.ru_utime+usage.ru_stime,peak_rss_mib=usage.ru_maxrss/1024)


if __name__=='__main__':
    root=Path(__file__).resolve().parent;request=json.loads(base64.b64decode(sys.argv[1],validate=True))
    if not 1<=len(request)<=6:raise ValueError('Batch size 1..6')
    directory=root/'data';directory.mkdir(exist_ok=True);results=[]
    for job in request:
        spec=job['dataset'];profile=spec['profile']
        if profile not in PROFILES or spec['version']!=VERSION or not 0<=spec['seed']<=1000000:raise ValueError('Invalid dataset')
        if any(spec[k]!=v for k,v in PROFILES[profile].items()):raise ValueError('Dataset profile mismatch')
        if job['action'] not in ('memory','stream','chunk','sqlite'):raise ValueError('Invalid action')
        path=directory/(profile+'-'+str(spec['seed'])+'.csv')
        if not path.exists():
            with path.open('w',encoding='utf-8',newline='') as output:write_csv(spec,output)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        execution=benchmark(root/'strategies.py',path,job['action'],spec['group'])
        results.append(dict(id=job['id'],dataset_sha256=digest,**execution))
    hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('guest.py','strategies.py','csv_data.py')}
    print(json.dumps(dict(source_hashes=hashes,results=results)))
