"""Host-side reward oracle; candidate code is executed only through the sandbox SDK."""
import base64
import hashlib
import json
from pathlib import Path
import shlex
import time
import uuid

from .task import TASK_ID, candidate, cases


def grade_case(case, execution):
    if execution.get('timed_out'):return False,'candidate_timeout'
    if execution.get('returncode')!=0:return False,'candidate_nonzero_exit'
    try: output=json.loads(execution['stdout'])
    except (ValueError,KeyError):return False,'invalid_json_output'
    if not isinstance(output,dict) or set(output)!= {'result'} or type(output['result']) is not int:
        return False,'invalid_output_contract'
    return (True,'passed') if output==case['expected'] else (False,'wrong_answer')


def evaluate_candidate(driver, template_ref, source, *, task_id=TASK_ID,user='sandbox',
                       case_timeout=3,on_resource=None,cleanup=False):
    tests=cases(task_id)
    item=candidate(source,0,'reward_input')
    if item['invalid_syntax']:
        return dict(reward=0.0,passed=0,total=len(tests),sandbox_id=None,task_id=task_id,
                    candidate_sha256=item['sha256'],cases=[],candidate_error=item['invalid_syntax'])
    started=time.perf_counter();sid=None;error=None;result=None
    try:
        sid=driver.create_sandbox(template_ref)
        if on_resource:on_resource('created',sid)
        directory='/tmp/agentsphere-miles-'+uuid.uuid4().hex
        driver.command(sid,'umask 077; mkdir -p '+shlex.quote(directory),user=user)
        driver.write(sid,directory+'/candidate.py',item['code'],user=user)
        driver.write(sid,directory+'/runner.py',Path(__file__).with_name('guest_runner.py').read_text(encoding='utf-8'),user=user)
        rows=[]
        for test in tests:
            # Only this test's input goes to the sandbox. Expected values stay here.
            payload=base64.b64encode(json.dumps(test['input']).encode()).decode()
            command='python3 '+shlex.quote(directory+'/runner.py')+' '+shlex.quote(directory+'/candidate.py')+' '+shlex.quote(payload)+' '+str(case_timeout)
            output=driver.command(sid,command,user=user,timeout=case_timeout+15)
            execution=json.loads(output['stdout'])
            if not isinstance(execution,dict) or not {'returncode','timed_out','stdout'} <= set(execution):
                raise RuntimeError('Invalid trusted runner envelope; reward unavailable')
            passed,reason=grade_case(test,execution)
            rows.append(dict(id=test['id'],input=test['input'],expected=test['expected'],passed=passed,reason=reason,execution=execution))
        count=sum(r['passed'] for r in rows)
        result=dict(reward=count/len(tests),passed=count,total=len(tests),cases=rows,sandbox_id=sid,
                    task_id=task_id,candidate_sha256=item['sha256'],elapsed_s=time.perf_counter()-started)
    except Exception as exc:
        error=exc
    finally:
        if cleanup and sid:
            try:
                deleted=driver.delete_sandbox(sid)
                if on_resource:on_resource('deleted',sid)
                if result is not None:result['cleanup']=deleted
            except Exception as cleanup_error:
                raise RuntimeError(f'Episode sandbox {sid} cleanup failed: {cleanup_error}; original error: {error}') from cleanup_error
    if error is not None:
        raise RuntimeError(f'RL infrastructure/evaluation failed; no reward issued; sandbox={sid}: {error}') from error
    return result
