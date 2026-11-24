from ...core.registry import DemoPackage, Field
from .actions import plan, prepare, execute

def source(case):
    import inspect
    from ...sdk import code_for
    from ...engine import Engine
    code = code_for(case)
    helpers = {'files':'seed_files','transfer':'verify_files','persisted':'verify_files','network':'internet'}
    if case in helpers: code += '\n\n' + inspect.getsource(getattr(Engine,helpers[case]))
    return code

def validate(config,case,mode):
    if case == 'template_build': config.require('image')

def validate_config(values, case):
    if case == 'build_logs' and bool(values['build_log_template_id']) != bool(values['build_log_build_id']):
        raise ValueError('查询已有 Build 时，Template ID 和 Build ID 必须同时填写；或同时留空查询本次构建')

CASES = (('check', '连接检查', '准备', '验证 SDK、patch、鉴权和端点，读取可见模板。', 'none', 'SDK 版本与服务端请求均通过'),
 ('template_list', '列举模板', '模板', '实时展示模板 ID、Build 状态与关联 Gateway。', 'none', '返回当前账号的模板列表'),
 ('template_create', '创建模板', '模板', '创建独立演示模板，已有模板始终保留。', 'none', '获得新的 Template ID 和 Build ID'),
 ('template_build', '构建模板', '模板', '从你配置的镜像异步构建；无需等待即可演示其他能力。', 'template', '服务端接受 Build，展示真实状态'),
 ('build_logs', '查看 Build 状态与日志', '模板', '查询指定或本次 Build；空日志不会被当作成功。', 'build', '实时状态、日志和失败原因'),
 ('sandbox_create', '创建沙箱', '沙箱', '优先使用已有 Ready 模板，将长时间构建与现场演示分开。', 'source', '创建并查询同一个 Sandbox ID'),
 ('sandbox_list', '列举沙箱', '沙箱', '读取当前运行与暂停实例，区分本工具资源和其他实例。', 'none', '返回真实运行状态'),
 ('command', '连接与执行命令', '沙箱', 'connect 进入已创建的实例，查看用户、工作目录和架构。', 'running', '命令退出码为 0'),
 ('files', '写入与读取文件', '文件', '把示例文本写入沙箱，再读取并比对内容。', 'running', '写入内容与读取内容一致'),
 ('transfer', '上传与下载', '文件', '上传二进制资料，下载后核对 SHA256。', 'running', '字节数和 SHA256 完全相同'),
 ('network', '访问公网', '沙箱', '从沙箱内部访问 www.baidu.com，展示 HTTP 状态。', 'running', 'HTTPS 返回 200'),
 ('pause', '暂停沙箱', '连续性', '挂起同一个沙箱，模拟 Agent 等待用户确认。', 'running', '状态变为 paused'),
 ('resume', 'Connect 恢复', '连续性', '预制一个已暂停实例，再 connect 恢复并执行命令。', 'paused', '原 Sandbox ID 恢复 running'),
 ('persisted', '恢复后检查文件', '连续性', '预制任务文件→暂停→恢复，真实读取文本及二进制。', 'persisted', '同一实例中内容及 SHA256 保留'),
 ('sandbox_delete', '删除沙箱', '清理', '删除本工具创建的实例并查询验证；不会删除外部沙箱。', 'running', '详情返回 404'),
 ('template_delete', '删除演示模板', '清理', '删除本工具创建的模板；用户提供的 Ready 模板保留。', 'template', '模板详情返回 404'))
DEFINITION = DemoPackage(id='basic',title='基础 SDK 能力',kind='capability',
    description='独立验证模板、构建、沙箱、文件和生命周期。', cases=CASES,
    prepare=prepare,execute=execute,plan=plan,source=source,validate=validate,validate_config=validate_config,
    execution_cases=('command','files','transfer','network','resume','persisted'),
    fields=(Field('build_log_template_id','日志来源 Template ID'),Field('build_log_build_id','日志来源 Build ID')),
    case_fields={row[0]: ('build_log_template_id','build_log_build_id') if row[0]=='build_logs' else () for row in CASES})
