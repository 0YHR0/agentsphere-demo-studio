import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = {
    'region': 'cn-southwest-2',
    'api_url': 'https://agentsandbox.cn-southwest-2.myhuaweicloud.com',
    'api_key': '', 'gateway_id': '', 'gateway_url': '', 'ready_template_id': '', 'template_source': 'existing',
    'image': '', 'start_cmd': '', 'ready_cmd': 'true', 'command_user': 'root',
    'command_cwd': '/', 'sandbox_timeout': 1800, 'cpu': 2, 'memory_mb': 8192,
    'arch': 'x86_64', 'build_log_template_id': '', 'build_log_build_id': '',
    'openclaw_cli': 'openclaw', 'openclaw_user': 'node',
    'model_base_url': '', 'model_id': '', 'model_api_key': '',
    'build_extensions_json': '', 'liveness_image': '', 'liveness_python': '/usr/bin/python3', 'liveness_template_ref': '',
}
SECRETS = {'api_key', 'model_api_key'}


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if not k.endswith('_configured') and any(s in k.lower() for s in
                   ('token', 'password', 'secret', 'api_key', 'apikey', 'authorization', 'cookie')) else redact(v, secrets))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'e2b_[A-Za-z0-9]+', '[REDACTED]', value)
        value = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', '[REDACTED PRIVATE KEY]', value, flags=re.S)
    return value


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.save-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Config:
    def __init__(self, directory):
        from .core.registry import get_registry
        self.registry = get_registry()
        self.defaults = {**DEFAULTS, **{f.key: f.default for f in self.registry.fields.values()
                                      if f.key not in DEFAULTS}}
        self.secret_keys = SECRETS | {f.key for f in self.registry.fields.values() if f.kind == 'secret'}
        self.directory = Path(directory)
        self.path = self.directory / 'config.json'
        self.private_fields_path = self.directory / 'config-private-fields.json'
        if self.private_fields_path.exists():
            self.secret_keys |= set(json.loads(self.private_fields_path.read_text(encoding='utf-8')))
        stored = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        self.data = {**self.defaults, **stored}
        if 'template_source' not in stored:
            self.data['template_source'] = ('both' if self.data['ready_template_id'] and self.data['image']
                                            else 'existing' if self.data['ready_template_id']
                                            else 'build' if self.data['image'] else 'existing')

    def public(self):
        return {**{k: v for k, v in self.data.items() if k in self.defaults and k not in self.secret_keys},
                **{k + '_configured': bool(self.data.get(k)) for k in self.secret_keys}}

    def save(self, incoming):
        unknown = set(incoming) - set(self.defaults)
        if unknown:
            raise ValueError('未知配置项：' + ', '.join(sorted(unknown)))
        data = dict(self.data)
        for k, v in incoming.items():
            if k not in ('sandbox_timeout', 'cpu', 'memory_mb') and not isinstance(v, str):
                raise ValueError(k + ' 必须为字符串')
            if k in self.secret_keys and v == '':
                continue  # Empty form fields preserve previously saved credentials.
            data[k] = v.strip() if isinstance(v, str) else v
        for k in ('api_url', 'gateway_url', 'model_base_url'):
            if not data[k]:
                continue
            if k == 'gateway_url' and '://' not in data[k]:
                data[k] = 'https://' + data[k]
            u = urlsplit(data[k])
            if u.scheme != 'https' or not u.hostname or u.username or u.password or u.fragment or u.query:
                raise ValueError(k + ' 必须是有效的 HTTPS 地址，且不含用户名、密码或 fragment')
            data[k] = data[k].rstrip('/')
        for k in ('gateway_id', 'build_log_template_id', 'build_log_build_id'):
            if data[k]:
                data[k] = str(UUID(data[k]))
        if data['liveness_template_ref']:
            parts = data['liveness_template_ref'].split(':')
            if len(parts) != 2:
                raise ValueError('探针模板引用必须为 Template ID:Build ID')
            data['liveness_template_ref'] = ':'.join(str(UUID(part)) for part in parts)
        if data['ready_template_id']:
            parts = data['ready_template_id'].split(':')
            if len(parts) not in (1, 2):
                raise ValueError('模板引用必须为 Template ID 或 Template ID:Build ID')
            data['ready_template_id'] = ':'.join(str(UUID(part)) for part in parts)
        for k in ('sandbox_timeout', 'cpu', 'memory_mb'):
            data[k] = int(data[k])
        if not 60 <= data['sandbox_timeout'] <= 86400:
            raise ValueError('沙箱超时请设置为 60–86400 秒')
        if data['cpu'] < 1 or data['memory_mb'] < 512:
            raise ValueError('CPU 和内存规格无效')
        if data['template_source'] not in ('existing', 'build', 'both'):
            raise ValueError('请选择已有模板、现场构建或两者结合的演示方式')
        from .probes import build_extensions
        build_extensions(data['build_extensions_json'])
        if data['arch'] not in ('x86_64', 'arm64'):
            raise ValueError('架构必须为 x86_64 或 arm64')
        # Private field names survive package removal or later metadata changes.
        atomic_json(self.private_fields_path, sorted(self.secret_keys))
        atomic_json(self.path, data)
        self.data = data
        return self.public()

    def require(self, *keys):
        missing = [k for k in keys if not self.data.get(k)]
        if missing:
            raise ValueError('请先完成环境配置：' + '、'.join(missing))

    def secrets(self):
        return [self.data.get(k, '') for k in self.secret_keys]
