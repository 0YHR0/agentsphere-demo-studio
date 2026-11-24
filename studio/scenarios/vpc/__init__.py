from ...core.registry import DemoPackage, Field


def prepare(engine, driver, case):
    from .workflow import prepare as setup
    return setup(engine, driver, case)


def execute(engine, driver, case):
    from .workflow import execute as run
    return run(engine, driver, case)


def plan(engine, case):
    return {'case': case, 'steps': ['核对已 Ready Build 的 VPC 出站配置',
        '创建或复用本场景专用沙箱，固定 Template ID:Build ID',
        '在沙箱内直接请求私网服务，记录真实响应；失败保留资源']}


def source(case):
    import inspect
    from .workflow import prepare, execute
    from ...sdk import SDK
    return '\n\n'.join(inspect.getsource(f) for f in (SDK.create_sandbox, SDK.command, prepare, execute))


def validate(config, case, mode):
    from .workflow import validate_settings
    validate_settings(config.data, case)


DEFINITION = DemoPackage(id='vpc', title='企业内网 HTTP / WebSocket', kind='scenario',
    description='让 AgentSphere 沙箱访问客户 VPC 内的 HTTP 与 WebSocket 服务，验证私网通信和连接保持。',
    cases=(
        ('vpc_prepare', '准备 VPC 业务沙箱', 'VPC', '验证 private Build 并创建场景专用沙箱。', 'vpc', 'Build 配置与专用 Sandbox ID'),
        ('vpc_http', '请求内网 HTTP 服务', 'VPC', '从专用沙箱直接访问私网健康接口。', 'vpc', 'HTTP 2xx、真实正文和请求耗时'),
        ('vpc_websocket', '保持内网 WebSocket 连接', 'VPC', '单次连接发送回显，包含无应用消息区间，不自动重连。', 'vpc', '握手成功、回显一致、无重连、空闲后继续收发'),
        ('vpc_cleanup', '释放本场景沙箱', 'VPC', '只删除此场景创建的实例，保留客户模板和其他场景。', 'vpc', '删除后查询 404'),
    ), prepare=prepare, execute=execute, plan=plan, source=source, validate=validate,
    prerequisites=('客户已构建 networkMode=private 的 Ready 模板，并关联当前 Gateway',
                   '沙箱镜像包含 Python 3 和 curl；WebSocket 目标提供文本回显',
                   'VPC 内已有 HTTP 和 WebSocket 回显服务，安全组与主机允许目标端口',
                   '填入实际 RFC1918 私网 IPv4 地址；不要使用 ECS 公网管理地址'),
    outcome='核对 VPC Build → 创建专用沙箱 → HTTP → WebSocket 与空闲回显 → 清理',
    config_action='vpc_prepare', fields=(
        Field('vpc_template_ref', 'VPC Template ID:Build ID', help='必须填写已 Ready 的固定构建，且出站模式为 private'),
        Field('vpc_http_url', '内网 HTTP URL', help='例如 http://私网IPv4:8080/health'),
        Field('vpc_ws_url', '内网 WebSocket 回显 URL', help='例如 ws://私网IPv4:8080/ws'),
        Field('vpc_duration_s', 'WebSocket 观察秒数', '30', 'number', '20–600 秒；默认 30，正式长连接可设为 600'),
        Field('vpc_idle_s', '无应用消息秒数', '10', 'number', '至少 5 秒，且观察时长需比空闲多至少 10 秒'),
    ))
