from ...core.registry import DemoPackage, Field

def prepare(engine,driver,case):
    from .workflow import prepare as setup
    return setup(engine,driver,case)
def execute(engine,driver,case):
    from .workflow import execute as run
    return run(engine,driver,case)
def plan(engine,case):
    return {'case':case,'steps':['先保存本场景模型、CLI 与运行用户配置','准备专用沙箱，按业务步骤执行','检查原沙箱与已有资料，不自动补跑模型任务']}
def source(case):
    import inspect
    from .workflow import prepare,execute,run_task
    from ...sdk import SDK
    method={'openclaw_probe':'command','openclaw_network':'command','openclaw_input':'write',
            'openclaw_task':'command','openclaw_download':'read','openclaw_pause':'pause',
            'openclaw_restore':'resume','openclaw_cleanup':'delete_sandbox'}[case]
    return '\n\n'.join(inspect.getsource(f) for f in (getattr(SDK,method),prepare,execute,run_task))
def validate(config,case,mode):
    if case=='openclaw_task' and mode=='run':config.require('model_base_url','model_id','model_api_key')

CASES=(('openclaw_probe',
  '准备 OpenClaw 环境',
  'OpenClaw',
  '使用配置中的 Ready 模板创建专用业务沙箱，并检查 CLI 与运行用户。',
  'openclaw',
  '专用 Sandbox ID 与实际 CLI 版本'),
 ('openclaw_network',
  '验证公网访问',
  'OpenClaw',
  '在业务沙箱中访问 www.baidu.com，检查出站网络。',
  'openclaw',
  'HTTPS 返回 200'),
 ('openclaw_input', '上传项目简报', 'OpenClaw', '以业务用户写入简报并读回比对，供下一步真实任务使用。', 'openclaw', '实际输入文件与原文一致'),
 ('openclaw_task',
  '生成交付摘要',
  'OpenClaw',
  'OpenClaw 读取上一步上传的简报，调用模型并保存交付摘要。',
  'openclaw',
  '真实模型调用与非空交付文件'),
 ('openclaw_download',
  '读取并下载交付物',
  'OpenClaw',
  '通过 SDK 读取生成的摘要，核对哈希后可下载到本机。',
  'openclaw',
  '交付文件 SHA256 与生成时一致'),
 ('openclaw_pause',
  '暂停等待人工确认',
  'OpenClaw',
  '保存简报和交付物的哈希，暂停当前业务沙箱。',
  'openclaw',
  '同一 Sandbox ID 进入 paused'),
 ('openclaw_restore',
  '恢复并核对交付物',
  'OpenClaw',
  'connect 恢复原业务实例，检查简报和交付文件，绝不重写资料。',
  'openclaw',
  '同一实例、同一简报与交付物 SHA256'),
 ('openclaw_cleanup',
  '结束并释放业务沙箱',
  'OpenClaw',
  '仅删除本场景创建的沙箱，保留基础演示沙箱和已有模板。',
  'openclaw',
  '业务沙箱详情返回 404'))
DEFINITION=DemoPackage(id='openclaw',title='OpenClaw 项目交付助手',kind='scenario',
    description='上传项目简报，让 OpenClaw 调用真实模型生成交付摘要；暂停后恢复同一业务现场。',
    cases=CASES,prepare=prepare,execute=execute,plan=plan,source=source,validate=validate,
    prerequisites=('配置 AgentSphere 与含 OpenClaw CLI 的 Ready 模板','填写 CLI、运行用户、模型 Base URL、模型 ID 和模型 Key','本机可访问模型；沙箱按步骤验证公网'),
    outcome='简报 → 真实模型任务 → Markdown 交付 → 暂停/恢复后 SHA256 核对',config_action='openclaw_task',
    fields=(Field('openclaw_cli','OpenClaw CLI','openclaw'),Field('openclaw_user','镜像内运行用户','node'),
            Field('model_base_url','模型 Base URL',kind='url'),Field('model_id','模型 ID'),
            Field('model_api_key','模型 API Key',kind='secret',help='仅保存在本机，留空保留已有值')),
    case_fields={'openclaw_probe':('openclaw_cli','openclaw_user')})
