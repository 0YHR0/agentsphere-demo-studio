"""A sequential business workflow with its own sandbox and durable evidence."""
import hashlib
import shlex
import uuid

from ...engine import BRIEF, now


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def prepare(engine, driver, case):
    run = engine.state.get('openclaw_run', {})
    resource = next((r for r in engine.state['sandboxes']
                     if r['sandbox_id'] == run.get('sandbox_id') and not r.get('deleted')), None)
    if case == 'openclaw_probe' and resource is None:
        source = engine.source_template(driver)
        sid = driver.create_sandbox(source)
        resource = dict(sandbox_id=sid, template_id=source.split(':')[0],
                        template_ref=source, build_id=source.split(':')[1],
                        owned=True, created_at=now(), state='creating', scene='openclaw')
        run = dict(sandbox_id=sid, directory='/tmp/agentsphere-openclaw-' + uuid.uuid4().hex[:12],
                   user=engine.config.data['openclaw_user'])
        engine.bind_scenario('openclaw', run)
        engine.ledger.record('sandbox', resource, 'openclaw', run['run_id'])
        engine.save()
        engine.wait_state(driver, resource, 'running')
    if not resource:
        raise RuntimeError('请先执行“准备 OpenClaw 环境”，创建本场景专用沙箱')
    engine.own('sandbox', resource)
    if case == 'openclaw_cleanup':
        return resource
    detail = driver.sandbox_detail(run['sandbox_id'])
    if detail is None:
        raise RuntimeError('原业务沙箱已不存在；请释放记录并重新准备环境，不会替换 ID 冒充恢复')
    if run['user'] != engine.config.data['openclaw_user']:
        raise RuntimeError('运行用户已改变，请恢复原用户或释放业务沙箱后重新准备')
    if case == 'openclaw_restore':
        if not run.get('paused') or detail['state'] != 'paused':
            raise RuntimeError('请先执行“暂停等待人工确认”；恢复不会自动重新暂停实例')
    elif detail['state'] != 'running':
        raise RuntimeError('业务沙箱已暂停，请先执行“恢复并核对交付物”')
    if case not in ('openclaw_probe', 'openclaw_restore') and not run.get('environment_verified'):
        raise RuntimeError('请先完成 OpenClaw CLI 环境检查')
    if case in ('openclaw_task', 'openclaw_input') and not run.get('network_verified'):
        raise RuntimeError('请先执行“验证公网访问”')
    if case == 'openclaw_task' and not run.get('input_path'):
        raise RuntimeError('请先上传项目简报；任务不会重新生成输入冒充上一步资料')
    if case in ('openclaw_download', 'openclaw_pause', 'openclaw_restore') and not run.get('artifact_path'):
        raise RuntimeError('请先完成摘要生成，再演示交付、暂停与恢复')
    return resource


def execute(engine, driver, case):
    resource = prepare(engine, driver, case)
    run = engine.state['openclaw_run']
    sid, user = run['sandbox_id'], run['user']
    if case == 'openclaw_probe':
        result = driver.command(sid, engine.config.data['openclaw_cli'] + ' --version', user=user)
        result.update(sandbox_id=sid, template_ref=resource['template_ref'])
        run['environment_verified'] = True
    elif case == 'openclaw_network':
        result = engine.internet(driver, sid)
        run['network_verified'] = True
    elif case == 'openclaw_input':
        directory = run['directory']
        driver.command(sid, 'umask 077; mkdir -p ' + shlex.quote(directory), user=user)
        path = directory + '/brief.txt'
        driver.write(sid, path, BRIEF, user=user)
        text = driver.read(sid, path, user=user)
        if text != BRIEF:
            raise RuntimeError('上传简报读回不一致')
        run.update(input_path=path, input_sha256=digest(text))
        # A new input invalidates previous deliverables.
        for key in ('artifact_path', 'artifact_sha256', 'paused'):
            run.pop(key, None)
        result = dict(input_path=path, text=text, sha256=digest(text))
    elif case == 'openclaw_task':
        if digest(driver.read(sid, run['input_path'], user=user)) != run['input_sha256']:
            raise RuntimeError('项目简报已改变，请重新上传并确认输入')
        # Clear the previous success before trying a new model run.
        run.pop('artifact_path', None)
        run.pop('artifact_sha256', None)
        engine.save()
        result = engine.openclaw_task(driver, sid, run['directory'] + '/task-' + uuid.uuid4().hex[:12], run['input_path'])
        run.update(artifact_path=result['artifact_path'], artifact_sha256=digest(result['artifact']))
        result['input_path'] = run['input_path']
    elif case == 'openclaw_cleanup':
        result = driver.delete_sandbox(sid)
        resource['deleted'] = True
        run['deleted'] = True
    else:
        if case == 'openclaw_restore':
            driver.resume(sid)
            engine.wait_state(driver, resource, 'running')
            # Persist connection success even if the following content check fails.
            run['paused'] = False
            engine.save()
        text = driver.read(sid, run['input_path'], user=user)
        artifact = driver.read(sid, run['artifact_path'], user=user)
        if digest(text) != run['input_sha256'] or digest(artifact) != run['artifact_sha256']:
            raise RuntimeError('简报或交付物 SHA256 不一致，保留现场供排查')
        result = dict(artifact=artifact, artifact_path=run['artifact_path'],
                      sha256=run['artifact_sha256'], input_preserved=True, artifact_preserved=True)
        if case == 'openclaw_pause':
            driver.pause(sid)
            engine.wait_state(driver, resource, 'paused')
            run['paused'] = True
            result = dict(state='paused', input_sha256=run['input_sha256'], artifact_sha256=run['artifact_sha256'])
        if case == 'openclaw_restore':
            result['same_sandbox_id'] = sid
    result['sandbox_id'] = sid
    engine.save()
    return result


def run_task(engine, driver, sandbox_id, directory=None, task_path=None):
    from ...relay import ModelRelay
    engine.config.require('model_base_url', 'model_id', 'model_api_key')
    c = engine.config.data
    user = c['openclaw_user']
    directory = directory or '/tmp/agentsphere-openclaw-' + uuid.uuid4().hex[:12]
    supplied_input = task_path is not None
    config_path = directory + '/openclaw.json'
    task_path = task_path or directory + '/brief.txt'
    driver.command(sandbox_id, 'umask 077; mkdir -p ' + shlex.quote(directory), user=user)
    relay = ModelRelay(driver, sandbox_id, directory, user, c, engine.log)
    try:
        local_url = relay.start()
        model = {'agents': {'defaults': {'model': {'primary': 'demo/' + c['model_id']},
                    'skipBootstrap': True, 'workspace': directory + '/workspace'}},
                 'tools': {'allow': ['read', 'write']},
                 'models': {'mode': 'merge', 'providers': {'demo': {
                    'baseUrl': local_url, 'apiKey': 'local-relay-placeholder',
                    'api': 'openai-completions', 'models': [{'id': c['model_id'], 'name': c['model_id']}]}}}}
        driver.write(sandbox_id, config_path, json.dumps(model), user=user)
        if not supplied_input:
            driver.write(sandbox_id, task_path, BRIEF, user=user)
        output_path = directory + '/workspace/delivery-summary.md'
        prompt = ('你是项目交付助手。读取文件 ' + task_path +
                  '，仅依据简报生成三条方案价值和两条实施前置条件。'
                  '将中文结果写入 ' + output_path +
                  '，然后回复正文。只操作本演示目录，不访问外部系统，不执行初始化或询问姓名。')
        command = ('OPENCLAW_CONFIG_PATH=' + shlex.quote(config_path) +
                   ' OPENCLAW_STATE_DIR=' + shlex.quote(directory + '/state') + ' ' +
                   c['openclaw_cli'] + ' agent --local --agent main --session-id ' +
                   shlex.quote(uuid.uuid4().hex) + ' --message ' + shlex.quote(prompt) + ' --json')
        result = driver.command(sandbox_id, command, user=user, timeout=240)
        if relay.error:
            raise RuntimeError(relay.error)
        artifact = driver.read(sandbox_id, output_path, user=user)
        if not artifact.strip():
            raise RuntimeError('OpenClaw 没有生成交付摘要文件')
        result.update(model_calls=relay.calls, model_key_location='local workstation only',
                      artifact_path=output_path, artifact=artifact,
                      note='真实 OpenClaw CLI 和模型调用。模型 Key 不进入沙箱，仅在本机用于请求模型提供商。')
        return result
    finally:
        relay.close()
