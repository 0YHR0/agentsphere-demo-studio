"""Dedicated HTTP liveness demonstration. Never inject faults into the active business sandbox."""
import base64
import json
import shlex
import time
from pathlib import Path

DIRECTORY = '/tmp/agentsphere-native-health'


def build_options(image, python='/usr/bin/python3'):
    source = Path(__file__).with_name('probe_service.py').read_bytes()
    encoded = base64.b64encode(source).decode()
    start = "sh -c " + shlex.quote('printf %s ' + encoded +
        ' | /usr/bin/base64 -d > /tmp/agentsphere-health-probe.py; exec ' +
        shlex.quote(python) + ' -u /tmp/agentsphere-health-probe.py')
    ready = shlex.quote(python) + ' -c ' + shlex.quote(
        "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:18080/health',timeout=2).status==200")
    return {'fromImage': image, 'steps': [], 'startCmd': start, 'readyCmd': ready,
            'invoke': {'protocol': 'HTTP', 'port': 18080},
            'livenessProbe': {'probeHandler': {'httpGet': {'path': '/health'}},
                'probeConfig': {'enabled': True, 'initialDelaySeconds': 5,
                    'timeoutSeconds': 1, 'periodSeconds': 5, 'failureThreshold': 3}}}


def compatible(detail):
    probe = detail.get('livenessProbe') or {}
    handler = probe.get('probeHandler') or {}
    return (probe.get('probeConfig', {}).get('enabled') is True and
            handler.get('httpGet', {}).get('path') == '/health' and
            (detail.get('invoke') or {}).get('port') == 18080 and
            '/tmp/agentsphere-health-probe.py' in detail.get('startCmd', ''))


def prepare(engine, driver):
    c = engine.config.data
    state = engine.state.setdefault('liveness_test', {})
    # This scene keeps its own resources and never replaces active_sandbox.
    template = next((r for r in engine.state['templates']
                     if r.get('template_id') == state.get('template_id') and not r.get('deleted')), None)
    reference = c.get('liveness_template_ref', '')
    if reference:
        tid, _, bid = reference.partition(':')
        if not bid:
            raise ValueError('探针测试模板需填写 Template ID:Build ID，且由本工具生成')
        resource = {'template_id': tid, 'build_id': bid}
    else:
        image = c.get('liveness_image') or c.get('image')
        if not image:
            raise ValueError('请先在存活探针场景中填写测试镜像，或提供本工具的已构建探针模板')
        if template is None or driver.template(template['template_id']) is None:
            template = driver.create_template()
            template['purpose'] = 'liveness'
            engine.state['templates'].append(template)
            state.update(template_id=template['template_id'], sandbox_id=None)
            engine.save()
        resource = template
        if not template.get('submitted'):
            template['request_body'] = build_options(image, c['liveness_python'])
            driver.submit_build(template, template['request_body'])
            template.update(submitted=True, status='building')
            engine.save()
            engine.log('已提交独立探针测试 Build；基础镜像须包含 Python 3 与 base64。')
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        if engine.stop.is_set():
            raise RuntimeError('已停止等待；探针测试资源保留')
        info = driver.build_logs(resource)
        if template is resource:
            template['status'] = info['status']
            engine.save()
        if str(info['status']).lower() == 'ready':
            break
        if str(info['status']).lower() in ('error', 'failed', 'cancelled'):
            raise RuntimeError('探针测试构建失败：' + str(info.get('reason')))
        engine.stop.wait(15)
    else:
        raise RuntimeError('等待探针测试 Build 超时')
    detail = driver.build_detail(resource)
    if not compatible(detail):
        raise RuntimeError('该 Build 不是兼容的独立探针测试模板；不会向普通业务服务注入故障')
    state.update(template_id=resource['template_id'], build_id=resource['build_id'],
                 build_detail={k: detail.get(k) for k in ('invoke', 'livenessProbe')})
    sandbox = next((r for r in engine.state['sandboxes']
                    if r.get('sandbox_id') == state.get('sandbox_id') and not r.get('deleted')), None)
    info = driver.sandbox_detail(sandbox['sandbox_id']) if sandbox else None
    if (info is None or info.get('detailedState') == 'Error' or
            sandbox.get('template_id') != resource['template_id'] or sandbox.get('build_id') != resource['build_id']):
        sid = driver.create_sandbox(resource['template_id'] + ':' + resource['build_id'])
        sandbox = {'sandbox_id': sid, 'template_id': resource['template_id'],
                   'build_id': resource['build_id'], 'owned': True, 'purpose': 'liveness', 'state': 'running'}
        engine.state['sandboxes'].append(sandbox)
        state['sandbox_id'] = sid
        engine.save()
        engine.log('已创建独立探针测试沙箱：' + sid)
    engine.own('sandbox', sandbox)
    if not driver.has_handle(state['sandbox_id']):
        driver.connect(state['sandbox_id'])
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        row = sample(driver, state['sandbox_id'], c['liveness_python'])
        if row.get('service', {}).get('health', {}).get('status') == 200:
            engine.log('测试服务已健康；点击演示后先确认健康基线，再注入 HTTP 503。')
            return
        if engine.stop.wait(2):
            raise RuntimeError('已停止等待服务启动')
    raise RuntimeError('测试 HTTP 服务未就绪，保留资源供排查')


PROBE = '''import json,pathlib,urllib.request,urllib.error,time
D=pathlib.Path('/tmp/agentsphere-native-health')
r={'at':time.time(),'identity':json.loads((D/'current.json').read_text()),'starts':(D/'starts.jsonl').read_text()}
for route in ('health','work'):
 try:
  with urllib.request.urlopen('http://127.0.0.1:18080/'+route,timeout=2) as a:r[route]={'status':a.status,'body':json.load(a)}
 except urllib.error.HTTPError as e:r[route]={'status':e.code}
 except Exception as e:r[route]={'error':type(e).__name__}
print(json.dumps(r))
'''


def sample(driver, sid, python):
    row = {'observed_at': time.time()}
    try:
        row['service'] = json.loads(driver.command(sid, shlex.quote(python) + ' -c ' + shlex.quote(PROBE), user='root', timeout=10, refresh_connection=False)['stdout'])
    except Exception as exc:
        row['connection_error'] = str(exc)
    detail = driver.sandbox_detail(sid)
    row['sandbox'] = {k: detail.get(k) for k in ('state', 'detailedState', 'errorMessage')} if detail else None
    return row


def verify(engine, driver):
    c, state = engine.config.data, engine.state['liveness_test']
    sid = state['sandbox_id']
    rows = []
    baseline = time.monotonic()
    while True:
        row = sample(driver, sid, c['liveness_python'])
        row['phase'] = 'healthy_baseline'
        rows.append(row)
        if (row.get('service', {}).get('health', {}).get('status') != 200 or
                (row.get('sandbox') or {}).get('detailedState') != 'Running'):
            raise RuntimeError('故障注入前健康基线未通过，未注入故障')
        if time.monotonic() - baseline >= 20:
            break
        if engine.stop.wait(5):
            raise RuntimeError('已停止；未注入故障')
    identity = rows[-1]['service']['identity']
    driver.command(sid, 'touch ' + DIRECTORY + '/unhealthy', user='root')
    injected = time.monotonic()
    engine.log('仅对独立测试沙箱注入 HTTP 503；不重启服务，观察平台实际处理。')
    detected_at, restarted_at = None, None
    while True:
        row = sample(driver, sid, c['liveness_python'])
        row.update(phase='http_503', elapsed_s=round(time.monotonic()-injected, 3))
        rows.append(row)
        state['last_observations'] = rows
        engine.save()
        info = row.get('sandbox') or {}
        if info.get('detailedState') == 'Error' and detected_at is None:
            detected_at = row['elapsed_s']
            engine.log('平台将沙箱标记为 Error：' + str(info.get('errorMessage')))
        service = row.get('service') or {}
        if service.get('health', {}).get('status') == 200 and service.get('identity') != identity:
            restarted_at = row['elapsed_s']
            engine.log('检测到服务身份变化且 HTTP 恢复 200。')
            break
        if time.monotonic()-injected >= 180:
            break
        if engine.stop.wait(5):
            raise RuntimeError('已停止观察；故障沙箱保留在演示资源中')
    latest = rows[-1].get('sandbox') or {}
    for resource in engine.state['sandboxes']:
        if resource['sandbox_id'] == sid:
            resource.update(state=latest.get('state', 'unknown'), detailed_state=latest.get('detailedState'),
                            error_message=latest.get('errorMessage'))
    engine.save()
    result = {'sandbox_id': sid, 'build': state['build_detail'], 'samples': rows,
              'detected_error_s': detected_at, 'service_restarted_s': restarted_at,
              'outcome': 'service_recovered' if restarted_at is not None else 'marked_error' if detected_at is not None else 'not_detected',
              'note': '异常被探针识别不等于业务自动重启。以 Error、错误信息、服务身份和真实 HTTP 结果分别判定。'}
    if detected_at is None and restarted_at is None:
        raise RuntimeError('观察 180 秒未确认探针识别异常；不得报告验证通过。')
    return result
