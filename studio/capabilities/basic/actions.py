"""Basic SDK demonstrations; runtime scheduling lives in Engine."""
from ...sdk import environment

def plan(engine, case):
    if case not in engine.registry.actions:
        raise ValueError('未知演示能力')
    prerequisite = engine.registry.actions[case]['prerequisite']
    steps = {
        'openclaw': ['先在本场景保存模型、CLI 与运行用户配置', '按业务步骤执行；后续步骤校验原沙箱与已有资料，不自动补跑任务'],
        'liveness': ['准备独立探针模板（首次需构建）', '验证 Build 中探针已启用', '创建专用测试沙箱并检查 HTTP 健康'],
        'none': ['检查环境配置'],
        'template': ['复用或创建本工具的演示模板'],
        'build': ['优先查询你指定的 Build；否则准备本次模板并提交异步构建'],
        'source': ['按所选方式验证已有模板，或构建新模板并等待就绪', '固定 Ready Build 后创建沙箱'],
        'running': ['验证 Ready 模板', '复用自有沙箱；不存在则创建', '已暂停时 connect 恢复'],
        'paused': ['准备一个运行中的自有沙箱', '暂停并确认 paused'],
        'persisted': ['准备运行中的自有沙箱', '写入文本和二进制并记录哈希',
                      '暂停并恢复同一沙箱'],
    }[prerequisite]
    return {'case': case, 'steps': steps, 'note': '只准备此能力需要的状态；已有模板不删除。'}

def prepare(engine, driver, case):
    prerequisite = engine.registry.actions[case]['prerequisite']
    if prerequisite == 'none':
        return
    if prerequisite == 'template':
        engine.ensure_template(driver)
    elif prerequisite == 'build':
        cfg = engine.config.data
        if not (cfg['build_log_template_id'] and cfg['build_log_build_id']):
            engine.ensure_build(driver)
    elif prerequisite == 'source':
        engine.source_template(driver)
    else:
        resource = engine.running(driver)
        if prerequisite in ('paused', 'persisted'):
            if prerequisite == 'persisted':
                engine.seed_files(driver, resource)
            driver.pause(resource['sandbox_id'])
            engine.wait_state(driver, resource, 'paused')
            engine.log('已暂停：' + resource['sandbox_id'])
            if prerequisite == 'persisted':
                driver.resume(resource['sandbox_id'])
                engine.wait_state(driver, resource, 'running')
                engine.log('已恢复原实例，等待执行文件保留检查。')

def execute(engine, driver, case):
    engine.log('执行 SDK 演示：' + engine.registry.actions[case]['title'])
    if case in ('check', 'template_list'):
        result = driver.list_templates()
        if case == 'check':
            result['sdk'] = environment()
        return result
    if case == 'template_create':
        return engine.ensure_template(driver)
    if case == 'template_build':
        resource = engine.ensure_build(driver)
        return driver.build_logs(resource)
    if case == 'build_logs':
        cfg = engine.config.data
        resource = ({'template_id': cfg['build_log_template_id'],
                     'build_id': cfg['build_log_build_id']} if
                    cfg['build_log_template_id'] and cfg['build_log_build_id'] else engine.resource('template'))
        return driver.build_logs(resource)
    if case == 'sandbox_create':
        resource = engine.running(driver)
        return driver.sandbox_detail(resource['sandbox_id'])
    if case == 'sandbox_list':
        result = driver.list_sandboxes()
        owned = {r['sandbox_id'] for r in engine.state['sandboxes']}
        for row in result['sandboxes']:
            row['owned_by_studio'] = row['sandbox_id'] in owned
        return result
    resource = engine.resource('sandbox')
    sid = resource['sandbox_id'] if resource else None
    if case == 'command':
        return driver.command(sid, 'echo agentsphere-demo-connected; id; pwd; uname -m')
    if case == 'network':
        return engine.internet(driver, sid)
    if case in ('files', 'transfer'):
        engine.seed_files(driver, resource)
        return engine.verify_files(driver, resource)
    if case == 'pause':
        driver.pause(sid)
        return engine.wait_state(driver, resource, 'paused')
    if case == 'resume':
        output = driver.resume(sid)
        detail = engine.wait_state(driver, resource, 'running')
        return {'same_sandbox_id': sid, 'detail': detail, 'command': output}
    if case == 'persisted':
        return engine.verify_files(driver, resource)
    if case == 'sandbox_delete':
        engine.own('sandbox', resource)
        output = driver.delete_sandbox(sid)
        resource['deleted'] = True
        engine.state['active_sandbox'] = None
        engine.state['files'] = {}
        engine.save()
        return output
    if case == 'template_delete':
        resource = engine.resource('template')
        engine.own('template', resource)
        if any(not s.get('deleted') and s['template_id'] == resource['template_id']
               for s in engine.state['sandboxes']):
            raise RuntimeError('该演示模板还有本工具创建的沙箱，请先在资源面板清理沙箱')
        result = driver.delete_template(resource['template_id'])
        resource['deleted'] = True
        engine.state['active_template'] = None
        engine.save()
        return result
    raise ValueError('未实现的能力')
