import ipaddress
import json
import shlex
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID


def private_url(value, schemes):
    u = urlsplit(value)
    if u.scheme not in schemes or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError('请填写不含凭据、查询参数的内网服务 URL')
    try:
        address = ipaddress.IPv4Address(u.hostname)
        allowed = any(address in ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
        port = u.port
    except ValueError:
        raise ValueError('VPC 场景请使用 RFC1918 私网 IPv4 和有效端口') from None
    if not allowed:
        raise ValueError('VPC 场景需要私网 IPv4，不能用公网或 loopback 地址证明 VPC 连通')
    return value


def validate_settings(config, case):
    if case == 'vpc_cleanup':
        return
    parts = config['vpc_template_ref'].split(':')
    try:
        if len(parts) != 2: raise ValueError()
        for part in parts: UUID(part)
    except ValueError:
        raise ValueError('请填写 VPC Template ID:Build ID') from None
    if case == 'vpc_http': private_url(config['vpc_http_url'], ('http', 'https'))
    if case == 'vpc_websocket':
        private_url(config['vpc_ws_url'], ('ws', 'wss'))
        try: duration, idle = int(config['vpc_duration_s']), int(config['vpc_idle_s'])
        except ValueError: raise ValueError('WebSocket 时长必须为整数') from None
        if not (20 <= duration <= 600 and 5 <= idle <= duration - 10):
            raise ValueError('观察 20–600 秒；空闲至少 5 秒且至少留 10 秒收发')
        if config['sandbox_timeout'] < duration + 25:
            raise ValueError('沙箱 timeout 需要至少大于 WebSocket 观察时长 25 秒')


def prepare(engine, driver, case):
    validate_settings(engine.config.data, case)
    run = engine.scenario_run('vpc')
    resource = next((r for r in engine.state['sandboxes'] if r['sandbox_id'] == run.get('sandbox_id') and not r.get('deleted')), None)
    if case == 'vpc_cleanup':
        return resource
    chosen = engine.config.data['vpc_template_ref']
    if resource:
        engine.own('sandbox', resource)
        if resource['template_ref'] != chosen:
            raise RuntimeError('VPC 模板已改变，请先清理本场景沙箱，再重新准备')
        if driver.sandbox_detail(resource['sandbox_id']) is None:
            raise RuntimeError('原 VPC 沙箱已不存在；不会替换实例冒充同一次验证，请先清理记录')
        engine.wait_state(driver, resource, 'running')
        return resource
    reference = engine.resolve_template(driver, chosen)
    tid, bid = reference.split(':')
    detail = driver.build_detail({'template_id': tid, 'build_id': bid})
    network = detail.get('networkConfiguration', {})
    if network.get('networkMode') != 'private':
        raise RuntimeError('所选 Build 未配置 private 出站，不能作为 VPC 场景')
    required = ('targetProjectId', 'targetVpcId', 'targetSubnetId')
    if not all(network.get(k) for k in required):
        raise RuntimeError('VPC Build 缺少 project/VPC/subnet 配置')
    sid = driver.create_sandbox(reference)
    run = engine.bind_scenario('vpc', {'sandbox_id': sid, 'template_ref': reference, 'network_configuration': network})
    resource = dict(sandbox_id=sid, template_id=tid, build_id=bid, template_ref=reference,
                    owned=True, state='creating', scene='vpc')
    engine.ledger.record('sandbox', resource, 'vpc', run['run_id'])
    engine.save()
    engine.wait_state(driver, resource, 'running')
    return resource


def execute(engine, driver, case):
    resource = prepare(engine, driver, case)
    if case == 'vpc_cleanup':
        if resource is None: return {'skipped': True, 'reason': '本场景没有待清理的自有沙箱'}
        sid = resource['sandbox_id']
        if driver.sandbox_detail(sid) is None:
            result = {'sandbox_id': sid, 'detail_http': 404}
        else: result = driver.delete_sandbox(sid)
        resource['deleted'] = True
        engine.scenario_run('vpc')['deleted'] = True
        engine.save()
        return result
    sid = resource['sandbox_id']
    cfg = engine.config.data
    if case == 'vpc_prepare':
        return {'sandbox_id': sid, 'template_ref': resource['template_ref'],
                'network_configuration': engine.scenario_run('vpc')['network_configuration']}
    if case == 'vpc_http':
        url = private_url(cfg['vpc_http_url'], ('http', 'https'))
        command = "curl --noproxy '*' --fail --silent --show-error --connect-timeout 5 --max-time 15 -w '\\n%{json}\\n' " + shlex.quote(url)
        value = driver.command(sid, command, user='root', timeout=25)
        lines = value['stdout'].rstrip().split('\n')
        metrics = json.loads(lines[-1])
        if not 200 <= metrics['http_code'] < 300:
            raise RuntimeError('VPC HTTP 未返回 2xx')
        return {'sandbox_id': sid, 'url': url, 'body': '\n'.join(lines[:-1]),
                'http_status': metrics['http_code'], 'elapsed_s': metrics['time_total'],
                'remote_ip': metrics.get('remote_ip')}
    url = private_url(cfg['vpc_ws_url'], ('ws', 'wss'))
    script = Path(__file__).with_name('ws_probe.py').read_text(encoding='utf-8')
    path = '/tmp/agentsphere-vpc-' + engine.scenario_run('vpc')['run_id'] + '.py'
    driver.write(sid, path, script, user='root')
    command = 'python3 ' + shlex.quote(path) + ' ' + shlex.quote(url) + ' ' + cfg['vpc_duration_s'] + ' ' + cfg['vpc_idle_s']
    value = driver.command(sid, command, user='root', timeout=int(cfg['vpc_duration_s']) + 25)
    result = json.loads(value['stdout'])
    if result.get('status') != 'passed':
        raise RuntimeError('WebSocket 验证失败：' + json.dumps(result, ensure_ascii=False))
    return dict(sandbox_id=sid, **result)
