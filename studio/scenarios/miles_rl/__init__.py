from ...core.registry import DemoPackage, Field


def prepare(engine, driver, case):
    from .workflow import prepare as setup
    return setup(engine, driver, case)


def execute(engine, driver, case):
    from .workflow import execute as run
    return run(engine, driver, case)


def plan(engine, case):
    return {'case':case,'steps':['核对 Ready 模板并准备本场景的 CPU 沙箱',
        '实时模型生成需显式执行；内置候选会标注为对照样本',
        '每个候选使用独立沙箱，测试期望值留在本机',
        '返回真实测试通过率，验证 Miles custom_rm 回调；不更新模型参数']}


def source(case):
    import inspect
    from .workflow import prepare, execute, generate_candidates
    from .evaluator import evaluate_candidate
    from .reward import reward
    from ...sdk import SDK
    return '\n\n'.join(inspect.getsource(f) for f in
        (SDK.create_sandbox,SDK.command,generate_candidates,evaluate_candidate,reward,prepare,execute))


def validate(config, case, mode):
    from .workflow import validate_settings
    validate_settings(config.data,case,mode)


def validate_config(values, case):
    from .workflow import validate_settings
    validate_settings(values,case,'save')


DEFINITION=DemoPackage(id='miles_rl',title='Miles RL · 沙箱执行与奖励闭环',kind='scenario',
    description='模型生成候选 Python 代码，每个候选在独立 AgentSphere 沙箱中执行；本机判定测试通过率并返回 Miles 奖励函数。CPU 沙箱负责环境与验证，GPU 训练留在外部 Miles 集群。',
    cases=(
        ('miles_prepare','准备 RL 沙箱环境','Miles RL','验证 Ready 模板、Python 3 与运行用户；不执行模型生成。','miles_rl','专用 Sandbox ID 与 Python 环境'),
        ('miles_rollout','生成候选代码','Miles RL','实时模型生成，或明确选择内置正负对照；本步不执行候选代码。','miles_rl','候选源码、来源和 SHA256'),
        ('miles_evaluate','执行测试并计算 reward','Miles RL','每个候选创建独立沙箱；测试期望值只留本机，reward=通过数/总数。','miles_rl','逐用例结果、真实 reward 和组内中心化信号'),
        ('miles_callback','验证 Miles 奖励回调','Miles RL','按 custom_rm(args,sample) 契约重新执行一个候选，返回float；不是发起GPU训练。','miles_rl','回调返回值与前次实测 reward 一致'),
        ('miles_export','导出奖励与接入说明','Miles RL','导出本轮奖励证据JSONL和固定版本的Miles接入说明。','miles_rl','可下载审计交付物；不冒充训练checkpoint'),
        ('miles_cleanup','释放本轮 RL 沙箱','Miles RL','只清理本场景登记的准备、候选和回调沙箱，保留客户模板。','miles_rl','沙箱删除后查询404'),
    ),prepare=prepare,execute=execute,plan=plan,source=source,validate=validate,validate_config=validate_config,
    prerequisites=('先连接 AgentSphere，并准备含 Python 3 的 Ready 模板；不需要沙箱 GPU',
        '运行用户必须存在；推荐非 root 用户。每轮会创建准备及候选执行沙箱，演示后统一清理',
        '实时模型模式需本机可访问的OpenAI兼容模型；内置对照模式不调用模型',
        '本案例验证 rollout 执行与 reward 回调，外部 Miles/SGLang/训练集群需另行准备'),
    outcome='候选代码 → 独立沙箱执行 → 本机判定reward → Miles回调 → 奖励审计导出 → 清理（不做梯度更新）',
    config_action='miles_prepare',fields=(
        Field('miles_template_ref','RL Ready Template ID:Build ID',help='可留空使用环境配置中的已有Ready模板；本场景不现场构建'),
        Field('miles_user','沙箱运行用户','sandbox',help='必须已存在于镜像，且可写/tmp；推荐非root用户'),
        Field('miles_candidate_mode','候选来源','model','select','内置对照的reward仍来自现场沙箱执行，不是模型学习结果',
              (('model','实时模型生成'),('builtin','内置正负对照（非模型rollout）'))),
        Field('miles_candidate_count','候选数量','2','number','2–4，每个候选使用独立沙箱'),
        Field('miles_model_base_url','模型 Base URL',kind='url',help='仅实时模型模式需要，例如https://模型服务/v1'),
        Field('miles_model_id','模型 ID',help='仅实时模型模式需要，也可使用你提供的兼容模型'),
        Field('miles_model_api_key','模型 API Key',kind='secret',help='仅实时模型模式需要；只在本机调用模型，不写入沙箱'),
        Field('miles_case_timeout_s','每个测试的子进程时限（秒）','3','number','1–10；超时是候选失败，网络/SDK故障则中止评分'),
    ))
