import json
import uuid

SCOPE='sdk_basics'
TEMPLATE_CASES=('template_sdk_build','build_delete','sdk_basics_cleanup')
ALLOWED={'network_configuration','invoke','env_vars','first_invoke_cmd','agencies','liveness_probe',
    'observability','session_storage_config','storage_config','api_headers','tags','skip_cache','description'}


def build_options(text):
    data=json.loads(text or '{}')
    if not isinstance(data,dict) or set(data)-ALLOWED:raise ValueError('构建扩展仅支持官网参数：'+', '.join(sorted(ALLOWED)))
    if 'api_headers' in data and (not isinstance(data['api_headers'],dict) or set(data['api_headers'])-{'X-Project-ID'}):
        raise ValueError('api_headers仅允许X-Project-ID；API鉴权来自本机连接配置')
    for key in ('network_configuration','invoke','env_vars','agencies','liveness_probe','observability','session_storage_config','storage_config'):
        if key in data and not isinstance(data[key],dict):raise ValueError(key+'必须是JSON对象')
    if 'env_vars' in data and any(not isinstance(k,str) or not isinstance(v,str) for k,v in data['env_vars'].items()):raise ValueError('env_vars必须为字符串字典')
    for key in ('first_invoke_cmd','tags'):
        if key in data and (not isinstance(data[key],list) or not data[key] or any(not isinstance(v,str) for v in data[key])):raise ValueError(key+'必须为非空字符串数组')
    if 'skip_cache' in data and type(data['skip_cache']) is not bool:raise ValueError('skip_cache必须为布尔值')
    return data


def validate(config,case,mode='run'):
    c=config.data
    if case=='template_sdk_build':config.require('image');build_options(c['extra_build_options_json'])
    if case=='sandbox_timeout' and not 60<=int(c['extra_timeout_seconds'])<=86400:raise ValueError('有效期必须为60–86400秒')
    ref=c.get('extra_template_ref','')
    if ref:
        try:
            parts=ref.split(':')
            if len(parts)!=2:raise ValueError()
            for value in parts:uuid.UUID(value)
        except ValueError:raise ValueError('请填写固定Template ID:Build ID') from None


def sandbox_resource(engine):
    sid=engine.state.get('sdk_basics_sandbox')
    return next((r for r in engine.state['sandboxes'] if r['sandbox_id']==sid and r.get('scope')==SCOPE),None)


def template_resource(engine):
    tid=engine.state.get('sdk_basics_template')
    return next((r for r in engine.state['templates'] if r['template_id']==tid and r.get('scope')==SCOPE),None)


def prepare(engine,driver,case):
    if case in TEMPLATE_CASES:return
    resource=sandbox_resource(engine)
    if resource and not resource.get('deleted'):
        engine.own('sandbox',resource)
        if driver.sandbox_detail(resource['sandbox_id']) is None:resource['deleted']=True;engine.save()
    if not resource or resource.get('deleted'):
        chosen=engine.config.data['extra_template_ref'] or engine.config.data['ready_template_id']
        if not chosen:raise RuntimeError('请填写Ready模板')
        ref=engine.resolve_template(driver,chosen)
        sid=driver.create_sandbox(ref,envs={'STUDIO_SANDBOX_ENV':'created-by-studio'})
        resource=dict(sandbox_id=sid,template_id=ref.split(':')[0],template_ref=ref,owned=True,state='creating')
        engine.ledger.record('sandbox',resource,SCOPE);engine.state['sdk_basics_sandbox']=sid;engine.save()
    engine.wait_state(driver,resource,'running')


def execute(engine,driver,case):
    if case=='template_sdk_build':
        previous=template_resource(engine)
        if previous and not previous.get('deleted'):raise RuntimeError('本组已有自有模板，请先回收后重新构建')
        def created(resource):
            engine.ledger.record('template',resource,SCOPE);engine.state['sdk_basics_template']=resource['template_id'];engine.save()
        result=driver.build_template_async(created,build_options(engine.config.data['extra_build_options_json']))
        resource=template_resource(engine)
        if not resource:raise RuntimeError('构建回调未登记资源，请核对服务端返回与请求记录')
        resource.update(result);engine.save();return result
    if case=='build_delete':
        resource=template_resource(engine);engine.own('template',resource)
        if any(r['template_id']==resource['template_id'] for r in driver.list_sandboxes()['sandboxes']):raise RuntimeError('该模板仍有沙箱使用，拒绝删除Build')
        result=driver.delete_build(resource);resource['build_deleted']=True;engine.save();return result
    if case=='sdk_basics_cleanup':
        deleted=[]
        for kind in ('sandbox','template'):
            for r in engine.state['sandboxes' if kind=='sandbox' else 'templates']:
                if r.get('scope')!=SCOPE or r.get('deleted'):continue
                engine.own(kind,r)
                if kind=='template' and any(s['template_id']==r['template_id'] for s in driver.list_sandboxes()['sandboxes']):raise RuntimeError('该模板仍被沙箱引用，保留模板')
                deleted.append(getattr(driver,'delete_'+kind)(r[kind+'_id']));r['deleted']=True;engine.save()
        return dict(deleted=deleted,other_resources_preserved=True)
    resource=sandbox_resource(engine);engine.own('sandbox',resource);sid=resource['sandbox_id']
    if case=='sandbox_info':return driver.sdk_info(sid)
    if case=='sandbox_metrics':return driver.sdk_metrics(sid)
    if case=='sandbox_timeout':return driver.sdk_timeout(sid,int(engine.config.data['extra_timeout_seconds']))
    if case=='sandbox_envs':return driver.sdk_envs(sid)
    if case=='command_stream':return driver.command_stream(sid,engine.log)
    if case in ('process_background','pty_session'):return getattr(driver,case)(sid)
    directory='/tmp/agentsphere-sdk-'+resource['run_id']+'/'+uuid.uuid4().hex
    return getattr(driver,case)(sid,directory)
