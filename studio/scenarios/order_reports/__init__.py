from ...core.registry import DemoPackage,Field


def prepare(engine,driver,case):
    from .workflow import prepare
    return prepare(engine,driver,case)


def execute(engine,driver,case):
    from .workflow import execute
    return execute(engine,driver,case)


def validate(config,case,mode):
    from .workflow import validate
    return validate(config.data,case)


def validate_config(values,case):
    from .workflow import validate
    return validate(values,case,saving=True)


def plan(engine,case):return {'steps':['准备官方Python/SQLite沙箱，生成模拟订单CSV','测初始策略与固定规则；训练只使用训练文件reward','在未参与训练的相同文件上交错复测三种策略，报告真实时间和峰值RSS','保存重载模型并回收本轮沙箱；不承诺RL胜过固定规则']}


def source(case):
    import inspect
    from .environment import install,measure,grade
    from .policy import update
    from .workflow import execute,rule_action,measure_controls,train_round,evaluate_routes
    from ...sdk import SDK
    functions={
        'orders_prepare':(SDK.create_sandbox,install),
        'orders_baseline':(measure_controls,rule_action,measure,SDK.command,grade),
        'orders_train':(train_round,update,measure,SDK.command),
        'orders_evaluate':(evaluate_routes,measure,SDK.command),
        'orders_checkpoint':(execute,),
        'orders_cleanup':(SDK.delete_sandbox,),
    }
    return '\n\n'.join(inspect.getsource(f) for f in functions[case])


def view(run):
    from .evidence import view
    return view(run)


DEFINITION=DemoPackage(id='order_reports',title='电商订单报表 Agent · CPU RL 策略优化',kind='scenario',
    description='客户提交订单CSV，Agent选择整表、流式、分块或SQLite生成销售/退款/分类报表。沙箱实测正确性、时间和峰值RSS，CPU更新工具选择策略；留出文件与固定规则公平对照。',
    prerequisites=('使用模拟业务数据；真实SDK执行与参数更新，不需要GPU、外部模型API或PyTorch',
        '专用Ready模板须含Linux、Python 3、SQLite和现有非root运行用户，可复用已验证的官方Python模板',
        '金额按整数分计算；报表错误reward=0，正确时再评价进程时间和内存',
        '12轮默认72次训练执行，留出评估36次；不保证优于规则，不将子进程指标当作云端到端耗时'),
    outcome='客户报表需求 → 路由工具 → 沙箱执行 → 正确性/成本奖励 → CPU更新 → 留出对照 → 模型重载与清理',
    cases=(
        ('orders_prepare','准备订单报表环境','订单报表','创建本场景独立沙箱，检查Python/SQLite并安装四种真实计算工具。','order_reports','专用Sandbox与合成CSV任务定义'),
        ('orders_baseline','对照组 · 测训练前基准','订单报表','整表策略与人工规则各执行3次，记录分数、时间、内存；不更新参数。','order_reports','校准集基准值；全部初始概率25%'),
        ('orders_train','强化学习 · 多轮执行与更新','订单报表','每轮执行6次，根据真实得分更新概率；记录每次结果和本轮概率增减。','order_reports','逐轮得分、6次执行结果、12项概率变化'),
        ('orders_evaluate','强化学习 · 最终同文件对照','订单报表','在新文件上重新测整表、人工规则及训练后策略，每组12次。','order_reports','同一验证集上的最终得分、时间、内存'),
        ('orders_checkpoint','保存重载并导出证据','订单报表','模型保存后重新加载，再次生成报表，导出模型和评估证据。','order_reports','参数与动作一致，真实重载报表正确'),
        ('orders_cleanup','回收订单场景沙箱','订单报表','仅删除本场景本轮实例，保留模型、证据和客户模板。','order_reports','删除后404'),
    ),prepare=prepare,execute=execute,plan=plan,source=source,validate=validate,validate_config=validate_config,
    config_action='orders_prepare',visualizer='order_router',recommended=True,view=view,fields=(
        Field('orders_template_ref','订单报表 Ready Template ID:Build ID',help='填写客户自己的Python/SQLite模板；不隐式使用小艺镜像或现场构建'),
        Field('orders_user','沙箱运行用户','sandbox',help='镜像中已存在的用户，需可写/tmp'),
        Field('orders_rounds','训练轮数','12','number','2–24，每轮6次真实执行；默认与固定规则比较，不保证获胜'),
        Field('orders_learning_rate','学习率','6','number','0.01–10，奖励由正确性、实测时间和峰值RSS共同决定'),
        Field('orders_seed','策略随机种子','7','number','0–100000；固定种子复现动作采样，实际性能仍有噪声'),
    ))
