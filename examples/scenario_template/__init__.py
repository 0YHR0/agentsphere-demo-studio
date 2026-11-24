"""Copy this directory into studio/scenarios/customer_example, then restart."""
import inspect

from studio.core.registry import DemoPackage, Field


def prepare(engine, driver, case):
    run = engine.scenario_run('customer_example')
    resource = next((r for r in engine.state['sandboxes'] if r['sandbox_id']==run.get('sandbox_id') and not r.get('deleted')),None)
    if case == 'customer_example_cleanup': return resource
    if resource is None:
        ref = engine.source_template(driver)
        sid = driver.create_sandbox(ref)
        run = engine.bind_scenario('customer_example', {'sandbox_id':sid})
        resource = dict(sandbox_id=sid,template_id=ref.split(':')[0],build_id=ref.split(':')[1],
                        template_ref=ref,owned=True,state='creating')
        engine.ledger.record('sandbox',resource,'customer_example',run['run_id'])
        engine.save()
    engine.own('sandbox',resource)
    engine.wait_state(driver,resource,'running')
    return resource


def execute(engine, driver, case):
    import shlex
    resource = prepare(engine,driver,case)
    if case == 'customer_example_cleanup':
        if resource is None: return {'skipped':True,'reason':'没有本场景待清理资源'}
        engine.own('sandbox',resource)
        result = driver.delete_sandbox(resource['sandbox_id'])
        resource['deleted']=True; engine.save()
        return result
    expected = engine.config.data['customer_example_message']
    result = driver.command(resource['sandbox_id'],'printf %s '+shlex.quote(expected))
    if result['stdout'] != expected:
        raise RuntimeError('实际输出与场景输入不一致')
    return result


def plan(engine, case):
    return {'case':case,'steps':['准备本场景专用沙箱','执行实际命令，验证结果']}


def source(case):
    from studio.sdk import SDK
    return '\n\n'.join(inspect.getsource(f) for f in (SDK.command,prepare,execute))


DEFINITION=DemoPackage(id='customer_example',title='客户场景模板',kind='scenario',
    description='替换此描述，清楚说明客户业务输入、处理和交付结果。',
    cases=(('customer_example_run','运行场景','客户场景','实际执行 SDK 命令','customer','成功执行命令'),
           ('customer_example_cleanup','释放本场景','客户场景','删除本场景自有实例','customer','删除后 404')),
    prepare=prepare,execute=execute,plan=plan,source=source,
    prerequisites=('先配置 AgentSphere 和 Ready 模板',),outcome='独立场景的实际 SDK 结果',
    config_action='customer_example_run',fields=(Field('customer_example_message','示例输入','hello'),))
