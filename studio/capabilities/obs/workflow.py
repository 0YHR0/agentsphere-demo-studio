import hashlib
import re
import shlex
import time
from uuid import UUID,uuid4

SCOPE='obs'
MOUNT='/mnt/agentsphere-obs'


def validate(config,case,mode='run'):
    if case=='obs_cleanup':return
    c=config.data
    try:
        tid,bid=c['obs_template_ref'].split(':');UUID(tid);UUID(bid)
    except (ValueError,KeyError):raise ValueError('请填写固定OBS Template ID:Build ID') from None
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',c['obs_bucket']):raise ValueError('请填写有效OBS桶名')
    prefix=c['obs_prefix']
    if prefix and (not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*',prefix) or len(prefix)>180):
        raise ValueError('测试前缀仅支持字母、数字、下划线、短横线与路径分隔符，不含空路径或..')


def current(engine):return engine.state.get('obs_run',{})


def check_config(engine,driver):
    c=engine.config.data
    ref=engine.resolve_template(driver,c['obs_template_ref']);tid,bid=ref.split(':')
    detail=driver.build_detail(dict(template_id=tid,build_id=bid))
    net=detail.get('networkConfiguration') or {}
    if net.get('networkMode')!='private' or not all(net.get(k) for k in ('targetProjectId','targetVpcId','targetSubnetId')):
        raise RuntimeError('OBS挂载需要完整VPC出站配置，不能用公网模板代替')
    if not (detail.get('agencies') or {}).get('runtimeAgency'):raise RuntimeError('Build缺少存储访问runtimeAgency委托')
    return ref


def create(engine,driver,run,read_only=False):
    sid=driver.create_obs_sandbox(run['template_ref'],run['bucket'],run['bucket_path'],MOUNT,read_only)
    r=dict(sandbox_id=sid,template_id=run['template_ref'].split(':')[0],template_ref=run['template_ref'],owned=True,
        read_only=read_only,bucket=run['bucket'],bucket_path=run['bucket_path'],state='creating')
    engine.ledger.record('sandbox',r,SCOPE,run['run_id'])
    run.setdefault('sandbox_ids',[]).append(sid);engine.state['obs_sandbox']=sid;engine.save()
    engine.wait_state(driver,r,'running')
    info=driver.obs_mount_info(sid,MOUNT);r['mount_info']=info['mount'];engine.save()
    return r


def resource(engine,sid):
    r=next((r for r in engine.state['sandboxes'] if r['sandbox_id']==sid and r.get('scope')==SCOPE),None)
    engine.own('sandbox',r);return r


def seed(engine,driver,run):
    if run.get('seeded'):return
    r=create(engine,driver,run);sid=r['sandbox_id'];run['writer_id']=sid;engine.save()
    path=MOUNT+'/'+run['test_dir']
    driver.connect(sid).files.make_dir(path,user='root',request_timeout=30)
    driver.write(sid,path+'/evidence.txt',run['expected'],user='root')
    driver.command(sid,'sync',user='root')
    actual=driver.read(sid,path+'/evidence.txt',user='root')
    if actual!=run['expected']:raise RuntimeError('OBS写入后内容不一致')
    run.update(seeded=True,sha256=hashlib.sha256(actual.encode()).hexdigest());engine.save()


def prepare(engine,driver,case):
    validate(engine.config,case)
    if case=='obs_cleanup':return
    ref=check_config(engine,driver);c=engine.config.data;run=current(engine)
    if run and not run.get('cleaned'):
        if (run['template_ref'],run['bucket'],run['prefix'])!=(ref,c['obs_bucket'],c['obs_prefix']):
            raise RuntimeError('本组仍有测试资源，请先回收后切换模板、桶或前缀')
    else:
        rid=uuid4().hex[:12]
        run=dict(run_id=rid,template_ref=ref,bucket=c['obs_bucket'],prefix=c['obs_prefix'],
            bucket_path=c['obs_prefix'],test_dir='run-'+rid,expected='AgentSphere OBS persistence '+rid+'\n',sandbox_ids=[])
        engine.state['obs_run']=run;engine.save()
    seed(engine,driver,run)


def execute(engine,driver,case):
    run=current(engine)
    if case=='obs_cleanup':return cleanup(engine,driver,run)
    if not run.get('seeded'):raise RuntimeError('请先准备OBS测试状态')
    path=MOUNT+'/'+run['test_dir']
    if case=='obs_write':
        sid=run.get('reader_id') or run['writer_id'];r=resource(engine,sid)
        engine.state['obs_sandbox']=sid;engine.save()
        if r.get('deleted') or driver.sandbox_detail(sid) is None:raise RuntimeError('测试沙箱已不存在，请回收本轮记录后重新准备')
        value=driver.read(sid,path+'/evidence.txt',user='root')
        if value!=run['expected']:raise RuntimeError('OBS文件内容不一致')
        return dict(sandbox_id=sid,bucket=run['bucket'],bucket_path=run['bucket_path'],test_directory=run['test_dir'],mount=r['mount_info'],sha256=run['sha256'],content=value)
    if case=='obs_persist':
        old=resource(engine,run['writer_id'])
        if not old.get('deleted'):
            driver.delete_sandbox(old['sandbox_id']);old['deleted']=True;engine.save()
        if driver.sandbox_detail(old['sandbox_id']) is not None:raise RuntimeError('原沙箱未删除')
        if not run.get('reader_id'):
            r=create(engine,driver,run);run['reader_id']=r['sandbox_id'];engine.save()
        sid=run['reader_id']
        engine.state['obs_sandbox']=sid;engine.save()
        if sid==old['sandbox_id']:raise RuntimeError('跨实例验证需要新Sandbox ID')
        # OBS flush and list consistency can lag briefly; never rewrite a missing file.
        deadline=time.monotonic()+30
        while True:
            try:
                value=driver.read(sid,path+'/evidence.txt',user='root')
                if value!=run['expected']:raise RuntimeError('新沙箱文件内容不一致')
                break
            except Exception:
                if time.monotonic()>=deadline:raise
                engine.stop.wait(2)
        return dict(sandbox_id=sid,original_sandbox_id=old['sandbox_id'],original_detail_http=404,
            different_sandbox=True,bucket_path=run['bucket_path'],test_directory=run['test_dir'],content=value,sha256=hashlib.sha256(value.encode()).hexdigest())
    if case=='obs_readonly':
        if not run.get('readonly_id'):
            r=create(engine,driver,run,True);run['readonly_id']=r['sandbox_id'];engine.save()
        engine.state['obs_sandbox']=run['readonly_id'];engine.save()
        return driver.obs_readonly_check(run['readonly_id'],path,run['expected'])
    raise ValueError('未知OBS用例')


def cleanup(engine,driver,run):
    if not run or run.get('cleaned'):return dict(skipped=True,reason='本轮无待回收OBS资源')
    owned=[resource(engine,sid) for sid in run.get('sandbox_ids',[])]
    live=[]
    for r in owned:
        if not r.get('deleted'):
            if driver.sandbox_detail(r['sandbox_id']) is None:r['deleted']=True;engine.save()
            else:live.append(r)
    # Only remove names generated by this workflow under its unique run prefix.
    if not run.get('objects_removed'):
        writer=next((r for r in live if not r['read_only']),None)
        if writer is None:
            writer=create(engine,driver,run);live.append(writer)
        sid=writer['sandbox_id'];driver.obs_mount_info(sid,MOUNT)
        sandbox=driver.connect(sid)
        for name in ('evidence.txt','readonly-denied.txt'):
            path=MOUNT+'/'+run['test_dir']+'/'+name
            if sandbox.files.exists(path,user='root',request_timeout=20):sandbox.files.remove(path,user='root',request_timeout=30)
            if sandbox.files.exists(path,user='root',request_timeout=20):raise RuntimeError('OBS测试文件未删除')
        directory=MOUNT+'/'+run['test_dir']
        if sandbox.files.exists(directory,user='root',request_timeout=20):
            if sandbox.files.list(directory,user='root',request_timeout=20):
                run['test_directory_retained']='目录中有额外对象，保留这些对象'
            else:
                # rmdir fails if another writer adds an object; never recursively erase it.
                driver.command(sid,'python3 -c '+shlex.quote('import os; os.rmdir('+repr(directory)+')'),user='root')
                run['test_directory_removed']=True
        driver.command(sid,'sync',user='root');run['objects_removed']=True;engine.save()
    deleted=[]
    for r in live:
        deleted.append(driver.delete_sandbox(r['sandbox_id']));r['deleted']=True;engine.save()
    run['cleaned']=True;engine.state['obs_sandbox']=None;engine.save()
    return dict(deleted=deleted,test_objects_removed=True,test_directory_removed=run.get('test_directory_removed',False),
        test_directory_retained=run.get('test_directory_retained'),bucket_preserved=True,template_preserved=True)
