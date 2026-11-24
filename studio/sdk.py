"""Official, pinned E2B SDK plus the wheel specified by Huawei documentation.

No Sandbox subclass, monkey patch, envd-version substitution, or SDK fork here.
Provider-only template fields use the generated SDK model's additional properties.
"""
import hashlib
import importlib.metadata
import inspect
import json
import shlex
import uuid
from datetime import datetime, timezone

from .config import ROOT
from .core.instrumentation import recorded
from .sdk_features import SDKFeatures


def environment():
    expected = json.loads((ROOT / 'sdk-versions.json').read_text(encoding='utf-8'))
    versions, errors = {}, []
    for name in ('e2b', 'e2b-code-interpreter', 'agentsphere-e2b-patch'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = '未安装'
        if versions[name] != expected[name]:
            errors.append(f'{name}: 需要 {expected[name]}，当前 {versions[name]}')
    patched = False
    if not errors:
        import agentsphere_e2b_patch  # noqa: F401 — must precede E2B imports
        from e2b import Sandbox
        patched = bool(getattr(Sandbox.__init__, '_agentsphere_e2b_patched', False))
        if not patched:
            errors.append('官网 patch 未加载')
    return {'versions': versions, 'patch_loaded': patched, 'errors': errors,
            'documentation': expected['documentation']}


class SDK(SDKFeatures):
    def __init__(self, config):
        env = environment()
        if env['errors']:
            raise RuntimeError('；'.join(env['errors']) + '。请运行启动脚本安装锁定依赖。')
        import agentsphere_e2b_patch  # noqa: F401
        from e2b import Sandbox, Template
        from e2b.api.client_sync import get_api_client
        from e2b.connection_config import ConnectionConfig
        self.Sandbox, self.Template = Sandbox, Template
        self._sandboxes = {}
        self.c = config
        self.options = {'api_key': config['api_key'], 'api_url': config['api_url'],
                        'request_timeout': 45}
        self.client = get_api_client(ConnectionConfig(**self.options))
        self.sandbox_options = {**self.options, 'sandbox_url': config['gateway_url'],
                                'headers': {'X-API-Key': config['api_key']}}

    def _http_event(self, method, path, response, body=None):
        recorder = getattr(self, 'recorder', None)
        if recorder:
            try:
                try: data = json.loads(response.content)
                except (ValueError, TypeError): data = response.content.decode('utf-8', 'replace')
                recorder({'layer': 'http', 'request': {'method': method,
                    'url': self.c['api_url'].rstrip('/')+path,
                    'headers': {'X-API-Key': '[REDACTED]'}, 'body': body},
                    'response': {'status': int(response.status_code), 'body': data}})
            except Exception as exc:
                self.recording_error = type(exc).__name__+': '+str(exc)

    @recorded
    def query(self, path, params=None, allow_missing=False):
        response = self.client.get_httpx_client().get(path, params=params)
        self._http_event('GET', path, response)
        if allow_missing and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    @recorded
    def list_templates(self):
        # Huawei returns Ready instead of the SDK enum ready: use SDK transport
        # and preserve raw provider values; never report this as a typed API call.
        rows, token = [], None
        for _ in range(100):
            params = {'limit': 100}
            if token:
                params['nextToken'] = token
            r = self.client.get_httpx_client().get('/v2/templates', params=params)
            self._http_event('GET', '/v2/templates', r)
            r.raise_for_status()
            rows.extend(r.json())
            token = r.headers.get('x-next-token') or r.headers.get('next-token')
            if not token:
                return {'templates': rows, 'transport': 'E2B SDK authenticated HTTP client'}
        raise RuntimeError('模板列表分页超过限制')

    @recorded
    def template(self, template_id):
        return self.query('/templates/' + template_id, allow_missing=True)

    @recorded
    def create_template(self):
        from e2b.api.client.api.templates import post_v3_templates
        from e2b.api.client.models import TemplateBuildRequestV3
        name = 'agentsphere-demo-' + uuid.uuid4().hex[:10]
        body = TemplateBuildRequestV3(name=name, cpu_count=self.c['cpu'],
                                      memory_mb=self.c['memory_mb'])
        body['gatewayID'] = self.c['gateway_id']
        body['arch'] = self.c['arch']
        r = post_v3_templates.sync_detailed(client=self.client, body=body)
        self._http_event('POST', '/v3/templates', r, body.to_dict())
        if not 200 <= r.status_code < 300:
            raise RuntimeError(f'创建模板 HTTP {r.status_code}: {r.content.decode()}')
        data = json.loads(r.content)
        return {'template_id': data['templateID'], 'build_id': data['buildID'],
                'name': name, 'status': 'waiting', 'owned': True}

    @recorded
    def submit_build(self, resource, build_options=None):
        from e2b.api.client.api.templates import post_v_2_templates_template_id_builds_build_id
        from e2b.api.client.models import TemplateBuildStartV2
        from .probes import build_extensions
        payload = {'fromImage': self.c['image'], 'steps': []}
        if self.c['start_cmd']:
            payload['startCmd'] = self.c['start_cmd']
        if self.c['ready_cmd']:
            payload['readyCmd'] = self.c['ready_cmd']
        payload.update(build_extensions(self.c.get('build_extensions_json', '')))
        if build_options is not None:
            payload = dict(build_options)
        # Huawei-only invoke / livenessProbe use generated additional_properties.
        # Official SDK and official patch versions remain unchanged.
        body = TemplateBuildStartV2.from_dict(payload)
        r = post_v_2_templates_template_id_builds_build_id.sync_detailed(
            resource['template_id'], resource['build_id'], client=self.client, body=body)
        self._http_event('POST', '/v2/templates/'+resource['template_id']+'/builds/'+resource['build_id'], r, body.to_dict())
        if not 200 <= r.status_code < 300:
            raise RuntimeError(f'提交 Build HTTP {r.status_code}: {r.content.decode()}')
        return {'http': int(r.status_code), 'template_id': resource['template_id'],
                'build_id': resource['build_id'], 'status': 'building'}

    @recorded
    def build_detail(self, resource):
        # Provider BuildDetail has fields absent from the typed upstream model.
        return self.query('/templates/' + resource['template_id'] + '/builds/' + resource['build_id'])

    @recorded
    def build_logs(self, resource):
        from e2b.template.types import BuildInfo
        name = resource.get('name', 'demo')
        info = BuildInfo(template_id=resource['template_id'], build_id=resource['build_id'],
                         name=name, alias=name, tags=[])
        result = self.Template.get_build_status(info, **self.options)
        detail = self.build_detail(resource)
        return {'template_id': resource['template_id'], 'build_id': resource['build_id'],
                'invoke': detail.get('invoke'), 'livenessProbe': detail.get('livenessProbe'),
                'status': result.status.value,
                'log_entries': [{'timestamp': str(e.timestamp), 'level': e.level,
                                 'message': e.message} for e in result.log_entries],
                'reason': str(result.reason) if result.reason else None}

    @recorded
    def sandbox_detail(self, sandbox_id):
        return self.query('/sandboxes/' + sandbox_id, allow_missing=True)

    @recorded
    def create_sandbox(self, template_ref,envs=None):
        # Engine resolves and validates an exact templateID:buildID before creation.
        sandbox = self.Sandbox.create(template_ref, timeout=self.c['sandbox_timeout'],**({'envs':envs} if envs is not None else {}),
                                       **self.sandbox_options)
        self._sandboxes[sandbox.sandbox_id] = sandbox
        # Return the ID first. The caller persists ownership before further queries.
        return sandbox.sandbox_id

    @recorded
    def connect(self, sandbox_id):
        # Both forms below are official SDK methods. The instance form retains
        # its original metadata and issues a real connect request without parsing
        # a replacement version. No fabricated versions or tokens.
        if sandbox_id not in self._sandboxes:
            self._sandboxes[sandbox_id] = self.Sandbox.connect(sandbox_id, timeout=self.c['sandbox_timeout'], **self.sandbox_options)
            return self._sandboxes[sandbox_id]
        return self._sandboxes[sandbox_id].connect(timeout=self.c['sandbox_timeout'], **self.sandbox_options)

    def has_handle(self, sandbox_id):
        return sandbox_id in self._sandboxes

    @recorded
    def command(self, sandbox_id, command, user=None, timeout=45, refresh_connection=True):
        sandbox = self.connect(sandbox_id) if refresh_connection else self._sandboxes[sandbox_id]
        r = sandbox.commands.run(command, user=user or self.c['command_user'],
                                 cwd=self.c['command_cwd'], timeout=timeout,
                                 request_timeout=timeout + 10)
        if r.exit_code != 0:
            raise RuntimeError(f'命令退出码 {r.exit_code}: {r.stderr}\n{r.stdout}')
        return {'command': command, 'stdout': r.stdout, 'stderr': r.stderr,
                'exit_code': r.exit_code, 'sandbox_id': sandbox_id}

    @recorded
    def write(self, sandbox_id, path, value, user=None):
        return self.connect(sandbox_id).files.write(path, value,
            user=user or self.c['command_user'], request_timeout=45)

    @recorded
    def read(self, sandbox_id, path, binary=False, user=None):
        return self.connect(sandbox_id).files.read(path, format='bytes' if binary else 'text',
            user=user or self.c['command_user'], request_timeout=45)

    @recorded
    def list_files(self, sandbox_id, path, user=None):
        return [entry.name for entry in self.connect(sandbox_id).files.list(
            path, user=user or self.c['command_user'], request_timeout=30)]

    @recorded
    def background(self, sandbox_id, command, user=None):
        return self.connect(sandbox_id).commands.run(command, background=True, timeout=0,
            user=user or self.c['command_user'], cwd=self.c['command_cwd'], request_timeout=45)

    @recorded
    def pause(self, sandbox_id):
        result = self.connect(sandbox_id).pause(request_timeout=60)
        return result

    @recorded
    def resume(self, sandbox_id):
        # Pause -> connect; no substitute ID or manual recreation.
        options = {**self.sandbox_options, 'request_timeout': 90}
        if sandbox_id in self._sandboxes:
            sandbox = self._sandboxes[sandbox_id].connect(timeout=self.c['sandbox_timeout'], **options)
        else:
            sandbox = self.Sandbox.connect(sandbox_id, timeout=self.c['sandbox_timeout'], **options)
        if sandbox.sandbox_id != sandbox_id:
            raise RuntimeError('恢复后的 Sandbox ID 与原实例不一致')
        self._sandboxes[sandbox_id] = sandbox
        return self.command(sandbox_id, 'echo resumed-ok; id; pwd')

    @recorded
    def list_sandboxes(self):
        from e2b import SandboxQuery, SandboxState
        rows = []
        for state in (SandboxState.RUNNING, SandboxState.PAUSED):
            paginator = self.Sandbox.list(query=SandboxQuery(state=[state]), limit=100, **self.options)
            for _ in range(100):
                rows.extend([{'sandbox_id': x.sandbox_id, 'template_id': x.template_id,
                              'state': str(x.state.value if hasattr(x.state, 'value') else x.state),
                              'started_at': str(x.started_at), 'end_at': str(x.end_at)}
                             for x in paginator.next_items()])
                if not paginator.has_next:
                    break
        return {'sandboxes': rows}

    @recorded
    def delete_sandbox(self, sandbox_id):
        self.Sandbox.kill(sandbox_id, **self.options)
        self._sandboxes.pop(sandbox_id, None)
        if self.sandbox_detail(sandbox_id) is not None:
            raise RuntimeError('删除请求后仍能查询到沙箱')
        return {'sandbox_id': sandbox_id, 'detail_http': 404}

    @recorded
    def delete_template(self, template_id):
        from e2b.api.client.api.templates import delete_templates_template_id
        r = delete_templates_template_id.sync_detailed(template_id, client=self.client)
        self._http_event('DELETE', '/templates/'+template_id, r)
        if r.status_code not in (200, 204, 404):
            raise RuntimeError(f'删除模板 HTTP {r.status_code}')
        if self.template(template_id) is not None:
            raise RuntimeError('删除后仍能查询到模板')
        return {'template_id': template_id, 'detail_http': 404}


def code_for(action):
    names = {'liveness': 'submit_build', 'check': 'list_templates', 'template_list': 'list_templates',
             'template_create': 'create_template', 'template_build': 'submit_build',
             'build_logs': 'build_logs', 'sandbox_create': 'create_sandbox',
             'sandbox_list': 'list_sandboxes', 'command': 'command', 'files': 'write',
             'transfer': 'read', 'network': 'command', 'pause': 'pause', 'resume': 'resume',
             'persisted': 'read', 'openclaw_probe': 'command', 'openclaw_task': 'command',
             'sandbox_delete': 'delete_sandbox', 'template_delete': 'delete_template'}
    if action.startswith('openclaw_'):
        names.update(openclaw_network='command', openclaw_input='write', openclaw_download='read',
                     openclaw_pause='pause', openclaw_restore='resume', openclaw_cleanup='delete_sandbox')
    return inspect.getsource(getattr(SDK, names[action]))
