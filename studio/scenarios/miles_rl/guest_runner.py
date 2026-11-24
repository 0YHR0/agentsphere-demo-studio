"""Trusted launcher inside an ephemeral Linux sandbox; contains no reward oracle."""
import base64
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


def run(candidate_path, payload, timeout):
    start=time.perf_counter()
    def limits():
        resource.setrlimit(resource.RLIMIT_CPU,(math.ceil(timeout)+1,math.ceil(timeout)+1))
        resource.setrlimit(resource.RLIMIT_AS,(256*1024**2,256*1024**2))
        resource.setrlimit(resource.RLIMIT_FSIZE,(8192,8192))
        resource.setrlimit(resource.RLIMIT_NOFILE,(32,32))
        resource.setrlimit(resource.RLIMIT_NPROC,(32,32))
    with tempfile.TemporaryDirectory(prefix='miles-case-') as directory:
        root=Path(directory)
        with (root/'stdout').open('w+b') as out,(root/'stderr').open('w+b') as err:
            child=subprocess.Popen([sys.executable,'-I',str(Path(candidate_path).resolve())],
                stdin=subprocess.PIPE,stdout=out,stderr=err,cwd=root,
                env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LANG':'C.UTF-8'},
                start_new_session=True,preexec_fn=limits)
            timed_out=False
            try:child.communicate(json.dumps(payload).encode(),timeout=timeout)
            except subprocess.TimeoutExpired:timed_out=True
            finally:
                # Kill descendants in this process group even if the parent exited.
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                child.wait()
            out.seek(0);stdout=out.read(8192).decode('utf-8','replace')
            err.seek(0);stderr=err.read(8192).decode('utf-8','replace')
    return dict(returncode=child.returncode,timed_out=timed_out,stdout=stdout,stderr=stderr,elapsed_s=time.perf_counter()-start)


if __name__=='__main__':
    value=json.loads(base64.b64decode(sys.argv[2],validate=True))
    print(json.dumps(run(sys.argv[1],value,float(sys.argv[3]))))
