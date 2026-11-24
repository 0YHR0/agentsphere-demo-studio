"""Validate Huawei build extensions without changing the pinned E2B SDK."""
import json


def build_extensions(value):
    if not value or not value.strip():
        return {}
    try:
        data = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise ValueError('构建扩展参数必须是有效 JSON') from exc
    if not isinstance(data, dict) or set(data) - {'invoke', 'livenessProbe'}:
        raise ValueError('构建扩展参数仅支持 invoke 和 livenessProbe')
    invoke = data.get('invoke')
    invoke = {} if invoke is None else invoke
    if not isinstance(invoke, dict):
        raise ValueError('invoke 必须是对象')
    probe = data.get('livenessProbe')
    if probe is not None and not isinstance(probe, dict):
        raise ValueError('livenessProbe 必须是对象')
    handler = (probe or {}).get('probeHandler')
    handler = {} if handler is None else handler
    if not isinstance(handler, dict):
        raise ValueError('probeHandler 必须是对象')
    for config in (invoke, handler.get('httpGet') or {}):
        if not isinstance(config, dict):
            raise ValueError('httpGet 必须是对象')
        if 'protocol' in config and config['protocol'] not in ('HTTP', 'HTTPS'):
            raise ValueError('protocol 必须为 HTTP 或 HTTPS')
        if 'port' in config and (type(config['port']) is not int or not 1 <= config['port'] <= 65535):
            raise ValueError('探针端口必须在 1–65535 之间')
    if probe is None:
        return data
    if not isinstance(probe, dict):
        raise ValueError('livenessProbe 必须是对象')
    handler, config = probe.get('probeHandler'), probe.get('probeConfig')
    handler = {} if handler is None else handler
    config = {} if config is None else config
    if not isinstance(handler, dict) or not isinstance(config, dict):
        raise ValueError('probeHandler / probeConfig 必须是对象')
    http, command = handler.get('httpGet'), handler.get('exec')
    if http is not None and command is not None:
        raise ValueError('httpGet 和 exec 只能选择一种')
    if config.get('enabled') is True and http is None and command is None:
        raise ValueError('enabled=true 时必须配置 httpGet 或 exec')
    if http is not None and (not isinstance(http, dict) or not isinstance(http.get('path'), str) or not http['path'].startswith('/')):
        raise ValueError('HTTP 探针 path 必填且以 / 开头')
    if command is not None:
        args = command.get('command') if isinstance(command, dict) else None
        if not isinstance(args, list) or not 1 <= len(args) <= 20 or any(not isinstance(v, str) or not v or len(v.encode('utf-8')) > 4096 for v in args):
            raise ValueError('Exec command 需含 1–20 个非空字符串参数，每个不超过 4096 字节')
    for key, value in config.items():
        if key == 'enabled':
            if type(value) is not bool:
                raise ValueError('enabled 必须为布尔值')
        elif type(value) is not int or value < 0:
            raise ValueError('探针时间和阈值必须为非负整数')
    if 'periodMilliseconds' in config and config['periodMilliseconds'] < 1000:
        raise ValueError('periodMilliseconds 至少为 1000')
    return data
