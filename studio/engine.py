import hashlib
import json
import shlex
import threading
import time
import uuid
from datetime import datetime, timezone

from .config import atomic_json, redact
from .sdk import SDK, environment
from .core.registry import get_registry
from .core.resources import ResourceLedger

BRIEF = ('客户：示例零售企业\n目标：部署一个能暂停恢复的客户服务 Agent\n'
         '要求：独立沙箱、保存任务文件、公网访问、按需回收资源\n'
         '验证目标：暂停后 Connect 恢复同一 Sandbox ID，并检查任务资料是否保留。\n'
         '本演示不包含跨实例 SFS 持久化，也没有验证外部会话存储、审计或自动归档。\n'
         '请据此输出三条解决方案价值、两条实施前置条件；不要虚构未验证的功能。\n')


def now():
    return datetime.now(timezone.utc).isoformat()


class Engine:
    def __init__(self, config, driver_factory=SDK):
        self.config, self.driver_factory = config, driver_factory
        self.registry = get_registry()
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.path = config.directory / 'session.json'
        self.state = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {
            'session_id': uuid.uuid4().hex[:12], 'templates': [], 'sandboxes': [],
            'active_template': None, 'active_sandbox': None, 'files': {}, 'jobs': []}
        self.state.setdefault('scenario_runs', {})
        if self.state.get('openclaw_run'):
            self.state['scenario_runs']['openclaw'] = self.state['openclaw_run']
        self.ledger = ResourceLedger(self.state, config)
        self.job = None
        self._driver = None
        self._driver_identity = None
        # A server restart never silently replays a previous mutation.
        for job in self.state['jobs']:
            if job['status'] == 'running':
                job.update(status='interrupted', error='后台重启，资源记录已保留，请重新查询状态。')
        self.save()

    def safe(self, value):
        return redact(value, self.config.secrets())

    def save(self):
        with self.lock:
            atomic_json(self.path, self.safe(self.state))

    def snapshot(self):
        with self.lock:
            runs={key:dict(run) for key,run in self.state['scenario_runs'].items()}
            for key,run in runs.items():
                package=self.registry.packages.get(key)
                if package and package.view:
                    run['display']=package.view(run)
            return self.safe({**self.state, 'busy': self.job is not None,
                              'scenario_runs':runs,
                              'config': self.config.public(), 'sdk': environment()})

    def log(self, text):
        with self.lock:
            if self.job:
                self.job['events'].append({'at': now(), 'message': self.safe(text)})
                self.save()

    def record_operation(self, event):
        with self.lock:
            if self.job:
                self.job.setdefault('operations', []).append(self.safe(event))
                self.job['operations'] = self.job['operations'][-200:]
                self.save()

    def resource(self, kind):
        key = self.state['active_' + kind]
        return next((r for r in self.state['sandboxes' if kind == 'sandbox' else 'templates']
                     if r[kind + '_id'] == key and not r.get('deleted')), None)

    def own(self, kind, resource):
        self.ledger.assert_owned(kind, resource)

    def scenario_run(self, scenario):
        return self.state['scenario_runs'].get(scenario, {})

    def bind_scenario(self, scenario, run):
        run.setdefault('run_id', uuid.uuid4().hex[:12])
        self.state['scenario_runs'][scenario] = run
        if scenario == 'openclaw':  # Read compatibility for existing local sessions.
            self.state['openclaw_run'] = run
        return run

    def export_report(self):
        from .core.reporting import export_report
        return export_report(self)

    def plan(self, case):
        return self.registry.package_for(case).plan(self, case)

    def start(self, case, mode='run', execution=None):
        if case not in self.registry.actions and case != 'cleanup':
            raise ValueError('未知演示能力')
        if mode not in ('run', 'prepare'):
            raise ValueError('无效执行方式')
        execution = {} if execution is None else execution
        if not isinstance(execution, dict) or set(execution) - {'command_user', 'command_cwd'}:
            raise ValueError('无效的场景执行参数')
        if execution and not self.registry.actions[case]['execution_params']:
            raise ValueError('此步骤不使用命令用户或工作目录参数')
        for key, value in execution.items():
            if not isinstance(value, str) or not value.strip() or any(ch in value for ch in ('\x00', '\n', '\r')):
                raise ValueError('执行参数必须为非空单行文本')
        if 'command_user' in execution and len(execution['command_user']) > 64:
            raise ValueError('执行用户名称过长')
        if 'command_cwd' in execution and (not execution['command_cwd'].startswith('/') or len(execution['command_cwd']) > 4096):
            raise ValueError('工作目录必须是沙箱内的绝对路径')
        execution = {k: v.strip() for k, v in execution.items()}
        with self.lock:
            if self.job:
                raise ValueError('当前操作尚未完成')
            self.config.require('api_url', 'api_key', 'gateway_id', 'gateway_url')
            package = self.registry.package_for(case) if case != 'cleanup' else None
            if package and package.validate:
                package.validate(self.config, case, mode)
            self.stop.clear()
            job = {'id': uuid.uuid4().hex[:12], 'case': case, 'mode': mode,
                   'status': 'running', 'started_at': now(), 'events': [],
                   'execution': execution}
            if package:
                job['package'] = package.id
                if package.kind == 'scenario':
                    run = self.scenario_run(package.id)
                    job.update(workflow=package.id+'-v1', scenario_id=package.id,
                               scenario_sandbox_id=run.get('sandbox_id'), run_id=run.get('run_id'))
            self.state['jobs'].append(job)
            self.state['jobs'] = self.state['jobs'][-100:]
            self.job = job
            self.save()
            threading.Thread(target=self._work, args=(case, mode, job), daemon=True).start()
            return job['id']

    def _work(self, case, mode, job):
        before = {id(r) for key in ('templates', 'sandboxes') for r in self.state[key]}
        try:
            runtime_config = {**self.config.data, **job.get('execution', {})}
            identity = tuple(self.config.data[k] for k in
                             ('api_url', 'api_key', 'gateway_id', 'gateway_url'))
            if self._driver is None or identity != self._driver_identity:
                self._driver = self.driver_factory(runtime_config)
                self._driver_identity = identity
            driver = self._driver
            driver.recorder = self.record_operation
            if hasattr(driver, 'c'):
                driver.c = runtime_config
            if job.get('execution'):
                self.log('本次场景执行参数：user=' + runtime_config['command_user'] +
                         '，cwd=' + runtime_config['command_cwd'])
            if case == 'cleanup':
                result = self.cleanup(driver)
            else:
                self.log('准备：' + self.registry.actions[case]['title'])
                self.prepare(case, driver)
                if job.get('scenario_id'):
                    run = self.scenario_run(job['scenario_id'])
                    job.update(scenario_sandbox_id=run.get('sandbox_id'), run_id=run.get('run_id'))
                    self.save()
                if self.stop.is_set():
                    raise RuntimeError('操作已停止，已创建资源保留在资源面板')
                result = {'prepared': True, 'plan': self.plan(case)} if mode == 'prepare' else self.execute(case, driver)
            job.update(status='skipped' if isinstance(result, dict) and result.get('skipped') else 'passed', result=self.safe(result))
            if getattr(driver, 'recording_error', None):
                job['recording_warning'] = self.safe(driver.recording_error)
        except Exception as exc:
            if job.get('scenario_id'):
                run = self.scenario_run(job['scenario_id'])
                job.update(scenario_sandbox_id=run.get('sandbox_id'), run_id=run.get('run_id'))
            job.update(status='cancelled' if self.stop.is_set() else 'failed',
                       error=self.safe(type(exc).__name__ + ': ' + str(exc)))
            self.log('操作结束，已有资源保留，可诊断、重试或清理。')
        finally:
            for key in ('templates', 'sandboxes'):
                for resource in self.state[key]:
                    if id(resource) not in before:
                        self.ledger.stamp(resource, job.get('package', 'basic'), job.get('run_id') or job['id'])
            if self._driver is not None and hasattr(self._driver, 'c'):
                self._driver.c = dict(self.config.data)
            with self.lock:
                job['finished_at'] = now()
                self.job = None
                self.save()

    def wait_state(self, driver, resource, state):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self.stop.is_set():
                raise RuntimeError('已停止等待')
            detail = driver.sandbox_detail(resource['sandbox_id'])
            if detail is None:
                resource['deleted'] = True
                self.save()
                raise RuntimeError('沙箱已不存在；不会用新 ID 冒充原实例恢复')
            resource.update(state=detail['state'], end_at=detail.get('endAt'))
            detailed = str(detail.get('detailedState') or detail['state']).lower()
            resource['detailed_state'] = detailed
            self.save()
            if detailed in ('error', 'failed'):
                raise RuntimeError('沙箱进入 Error：' + str(detail.get('errorMessage') or detailed))
            if detailed == state:
                return detail
            self.stop.wait(2)
        raise RuntimeError('等待沙箱状态超时，资源保留')

    def ensure_template(self, driver):
        resource = self.resource('template')
        if resource:
            self.own('template', resource)
        if resource and driver.template(resource['template_id']) is not None:
            return resource
        resource = driver.create_template()
        self.ledger.record('template', resource)
        self.state['active_template'] = resource['template_id']
        self.save()
        self.log('创建演示模板：' + resource['template_id'])
        return resource

    def ensure_build(self, driver):
        self.config.require('image')
        resource = self.ensure_template(driver)
        if not resource.get('submitted'):
            driver.submit_build(resource)
            resource.update(submitted=True, status='building')
            self.save()
            self.log('已提交 Build：' + resource['build_id'])
        return resource

    def source_template(self, driver):
        mode = self.config.data['template_source']
        chosen = self.config.data['ready_template_id'] if mode != 'build' else ''
        if mode in ('existing', 'both') and not chosen:
            raise RuntimeError('请在环境配置中填写已构建模板，或选择现场构建新模板')
        if not chosen:
            resource = self.ensure_build(driver)
            self.log('已选择现场构建，等待本次 Build；如需跳过等待，可停止后切换为已有模板或组合演示。')
            deadline = time.monotonic() + 1200
            while time.monotonic() < deadline:
                if self.stop.is_set():
                    raise RuntimeError('已停止等待 Build，资源保留')
                status = driver.build_logs(resource)
                resource['status'] = status['status']
                self.save()
                self.log('Build 状态：' + status['status'])
                if status['status'] == 'ready':
                    break
                if status['status'] in ('error', 'failed', 'cancelled'):
                    raise RuntimeError('Build 失败：' + str(status.get('reason')))
                self.stop.wait(15)
            else:
                raise RuntimeError('等待 Build 超时，资源保留')
            chosen = resource['template_id'] + ':' + resource['build_id']
        return self.resolve_template(driver, chosen)

    def resolve_template(self, driver, chosen):
        template_id, _, build_id = chosen.partition(':')
        detail = driver.template(template_id)
        if detail is None:
            raise RuntimeError('来源模板不存在')
        if detail.get('gatewayID') != self.config.data['gateway_id']:
            raise RuntimeError('来源模板 Gateway ID 与配置不一致，请核对对应的域名')
        ready_builds = [b for b in detail.get('builds', [])
                        if str(b.get('status', '')).lower() == 'ready' and b.get('buildID')]
        if build_id:
            if not any(b['buildID'] == build_id for b in ready_builds):
                raise RuntimeError('指定的 Build 不存在或尚未 Ready；不会替换为其他构建版本')
        else:
            if not ready_builds:
                raise RuntimeError('来源模板没有 Ready Build')
            latest = max(ready_builds, key=lambda b: b.get('createdAt') or b.get('updatedAt') or '')
            build_id = latest['buildID']
        reference = template_id + ':' + build_id
        self.log('新沙箱固定使用模板构建：' + reference)
        return reference

    def running(self, driver):
        resource = self.resource('sandbox')
        if resource:
            self.own('sandbox', resource)
            detail = driver.sandbox_detail(resource['sandbox_id'])
            if detail is None:
                resource['deleted'] = True
                self.state['files'] = {}
                self.save()
                self.log('先前自有沙箱已到期，准备新的实例。')
                resource = None
            elif detail.get('envdVersion') == '' and not driver.has_handle(resource['sandbox_id']):
                self.log('旧实例缺少 envdVersion 且本机句柄已丢失；保留旧资源，明确准备一个新演示实例。')
                resource = None
                self.state['active_sandbox'] = None
                self.state['files'] = {}
                self.save()
            elif detail['state'] == 'paused':
                self.wait_state(driver, resource, 'paused')
                driver.resume(resource['sandbox_id'])
                self.log('恢复同一实例：' + resource['sandbox_id'])
        if resource is None:
            source = self.source_template(driver)
            sid = driver.create_sandbox(source)
            resource = {'sandbox_id': sid, 'template_id': source.split(':', 1)[0],
                        'build_id': source.split(':', 1)[1], 'template_ref': source,
                        'owned': True, 'created_at': now(), 'state': 'creating'}
            self.ledger.record('sandbox', resource)
            self.state['active_sandbox'] = sid
            self.state['files'] = {}
            self.save()
            self.log('创建自有沙箱：' + sid)
        self.own('sandbox', resource)
        self.wait_state(driver, resource, 'running')
        return resource

    def seed_files(self, driver, resource):
        sid = resource['sandbox_id']
        marker = '/tmp/agentsphere-demo-' + self.state['session_id']
        text = BRIEF + '演示会话：' + self.state['session_id'] + '\n'
        binary = ('AgentSphere\x00OpenClaw\n' * 4096).encode('utf-8')
        driver.write(sid, marker + '/brief.txt', text)
        driver.write(sid, marker + '/input.bin', binary)
        self.state['files'] = {'sandbox_id': sid, 'text_path': marker + '/brief.txt',
            'binary_path': marker + '/input.bin', 'expected_text': text,
            'sha256': hashlib.sha256(binary).hexdigest(), 'bytes': len(binary)}
        self.save()
        self.log('已写入任务简报和二进制资料，并保存预期 SHA256。')
        return self.state['files']

    def prepare(self, case, driver):
        return self.registry.package_for(case).prepare(self, driver, case)

    def execute(self, case, driver):
        return self.registry.package_for(case).execute(self, driver, case)

    def internet(self, driver, sandbox_id):
        result = driver.command(sandbox_id,
            "curl -4 --noproxy '*' --connect-timeout 8 --max-time 20 -L -sS "
            "-o /dev/null -w 'HTTP=%{http_code} IP=%{remote_ip}\\n' https://www.baidu.com")
        if 'HTTP=200 ' not in result['stdout']:
            raise RuntimeError('公网请求未返回 200：' + result['stdout'])
        return result

    def verify_files(self, driver, resource):
        files = self.state['files']
        sid = resource['sandbox_id']
        if files.get('sandbox_id') != sid:
            raise RuntimeError('文件检查必须使用写入时的同一个 Sandbox ID')
        text = driver.read(sid, files['text_path'])
        binary = bytes(driver.read(sid, files['binary_path'], binary=True))
        digest = hashlib.sha256(binary).hexdigest()
        if text != files['expected_text'] or digest != files['sha256']:
            raise RuntimeError('文本内容或二进制 SHA256 不一致，保留资源供排查')
        return {'sandbox_id': sid, 'text_preserved': True, 'binary_preserved': True,
                'text': text, 'bytes': len(binary), 'sha256': digest,
                'paths': [files['text_path'], files['binary_path']]}

    def openclaw_task(self, driver, sandbox_id, directory=None, task_path=None):
        # Compatibility hook used by existing integrations and tests.
        from .scenarios.openclaw.workflow import run_task
        return run_task(self, driver, sandbox_id, directory, task_path)

    def cleanup(self, driver):
        results, errors = [], []
        for kind in ('sandbox', 'template'):
            for resource in self.state['sandboxes' if kind == 'sandbox' else 'templates']:
                if resource.get('deleted'):
                    continue
                try:
                    self.own(kind, resource)
                    if kind == 'template' and any(not s.get('deleted') and
                       s['template_id'] == resource['template_id'] for s in self.state['sandboxes']):
                        raise RuntimeError('沙箱未清理完成，保留其模板')
                    self.log('清理自有' + kind + '：' + resource[kind + '_id'])
                    result = getattr(driver, 'delete_' + kind)(resource[kind + '_id'])
                    resource['deleted'] = True
                    results.append(result)
                    self.save()
                except Exception as exc:
                    errors.append(str(exc))
        if errors:
            raise RuntimeError('部分资源清理失败：' + '；'.join(errors))
        self.state.update(active_sandbox=None, active_template=None, files={})
        self.save()
        return {'cleaned': results, 'external_templates_preserved': True}
