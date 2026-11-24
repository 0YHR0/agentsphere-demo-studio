"""Host-owned exact oracle, reward, and real SDK benchmark transport."""
import base64
from functools import lru_cache
import hashlib
import io
import json
import math
from pathlib import Path
import shlex

from .csv_data import PROFILES,VERSION,write_csv
from .policy import ACTIONS

SOURCE_NAMES=('guest.py','strategies.py','csv_data.py')


def source_hashes():return {name:hashlib.sha256(Path(__file__).with_name(name).read_text(encoding='utf-8').encode()).hexdigest() for name in SOURCE_NAMES}


@lru_cache(maxsize=192)
def reference(profile,seed):
    config=PROFILES[profile];totals=[0,0,0,0];groups={}
    # Independent arithmetic oracle: does not run any strategy implementation.
    for index in range(config['rows']):
        if (index+seed)%17==0:continue
        gross=((index+seed)%5+1)*((index*37+seed*13)%9901+99)
        refund=gross//2 if (index*3+seed)%11==0 else 0
        values=(1,gross,refund,gross-refund)
        totals=[a+b for a,b in zip(totals,values)]
        if config['group']:
            key=f'category_{(index+seed)%8:02d}' if config['group']=='category' else f'C{(index*17+seed)%config["customers"]:06d}'
            groups[key]=[a+b for a,b in zip(groups.get(key,[0]*4),values)]
    keys=('paid_orders','gross_cents','refund_cents','net_cents')
    return dict(**dict(zip(keys,totals)),groups={name:dict(zip(keys,v)) for name,v in groups.items()})


@lru_cache(maxsize=192)
def dataset_digest(profile,seed):
    stream=io.StringIO(newline='');write_csv(dict(profile=profile,seed=seed,**PROFILES[profile]),stream)
    return hashlib.sha256(stream.getvalue().encode()).hexdigest()


def grade(dataset,execution):
    needed=('returncode','timed_out','stdout','wall_s','peak_rss_mib','cpu_s')
    if not isinstance(execution,dict) or any(k not in execution for k in needed):raise RuntimeError('Missing benchmark envelope; no reward')
    for key in ('wall_s','peak_rss_mib','cpu_s'):
        if type(execution[key]) not in (int,float) or not math.isfinite(execution[key]) or execution[key]<0:
            raise RuntimeError('Invalid benchmark metrics; no reward')
    expected=reference(dataset['profile'],dataset['seed']);output=None
    try:output=json.loads(execution['stdout'])
    except ValueError:pass
    # Strict JSON integer contract: bool/float must not masquerade as cents/counts.
    def exact(a,b):
        if type(a) is not type(b):return False
        if isinstance(b,dict):return set(a)==set(b) and all(exact(a[k],v) for k,v in b.items())
        return a==b
    correct=execution['returncode']==0 and execution['timed_out'] is False and exact(output,expected)
    profile=PROFILES[dataset['profile']]
    time_cost=.6*execution['wall_s']/profile['time_budget_s'];memory_cost=.4*execution['peak_rss_mib']/profile['memory_budget_mib']
    reward=1/(1+time_cost+memory_cost) if correct else 0.0
    return dict(correct=correct,reward=reward,time_cost=time_cost,memory_cost=memory_cost,
        wall_s=execution['wall_s'],cpu_s=execution['cpu_s'],peak_rss_mib=execution['peak_rss_mib'],
        returncode=execution['returncode'],timed_out=execution['timed_out'],stderr=execution.get('stderr',''),
        report_sha256=hashlib.sha256(execution['stdout'].encode()).hexdigest(),
        report_preview=dict(totals={k:v for k,v in expected.items() if k!='groups'},group_count=len(expected['groups']),sample_groups=dict(list(expected['groups'].items())[:3])) if correct else None)


def install(driver,run):
    sid=run['sandbox_id'];user=run['user'];directory=run['directory']
    result=driver.command(sid,'umask 077; mkdir -p '+shlex.quote(directory)+" && python3 -c 'import csv,sqlite3,resource,os,sys; print(sys.version); print(\"uid=\"+str(os.getuid()))'",user=user)
    for name in SOURCE_NAMES:driver.write(sid,directory+'/'+name,Path(__file__).with_name(name).read_text(encoding='utf-8'),user=user)
    return result


def measure(driver,run,jobs):
    encoded=base64.b64encode(json.dumps([dict(id=j['id'],action=ACTIONS[j['action']],dataset=j['dataset']) for j in jobs]).encode()).decode()
    result=driver.command(run['sandbox_id'],'python3 '+shlex.quote(run['directory']+'/guest.py')+' '+shlex.quote(encoded),user=run['user'],timeout=90)
    envelope=json.loads(result['stdout'])
    if envelope.get('source_hashes')!=source_hashes():raise RuntimeError('Benchmark source changed; no reward')
    rows=envelope.get('results')
    if not isinstance(rows,list) or len(rows)!=len(jobs):raise RuntimeError('Incomplete benchmark results; no reward')
    observations=[]
    for job,row in zip(jobs,rows):
        if row.get('id')!=job['id'] or row.get('dataset_sha256')!=dataset_digest(job['task'],job['dataset']['seed']):
            raise RuntimeError('Benchmark dataset/job mismatch; no reward')
        observations.append(dict(**job,**grade(job['dataset'],row),dataset_sha256=row['dataset_sha256'],sandbox_id=run['sandbox_id']))
    return observations
