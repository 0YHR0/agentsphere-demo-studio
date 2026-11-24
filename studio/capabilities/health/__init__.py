from ...core.registry import DemoPackage, Field

def prepare(engine,driver,case):
    from ...liveness import prepare as prepare_probe
    return prepare_probe(engine,driver)
def execute(engine,driver,case):
    from ...liveness import verify
    return verify(engine,driver)
def plan(engine,case):
    return {'case':case,'steps':['准备独立探针模板（首次需构建）','验证 Build 中探针已启用','创建专用测试沙箱并检查 HTTP 健康']}
def source(case):
    import inspect
    from ...liveness import build_options,verify
    from ...sdk import code_for
    return code_for(case)+'\n\n'+inspect.getsource(build_options)+'\n\n'+inspect.getsource(verify)
DEFINITION=DemoPackage(id='health',title='健康探针',kind='capability',description='独立的健康检查与故障注入。',
    cases=(('liveness', '存活探针与故障检测', '健康检查', '独立测试服务 → 健康基线 → HTTP 503，观察平台状态、连接与恢复行为。', 'liveness', '探针识别异常，并区分标记 Error 与业务自动恢复'),),prepare=prepare,execute=execute,plan=plan,source=source,
    fields=(Field('liveness_image','探针镜像'),Field('liveness_python','Python 路径','/usr/bin/python3'),Field('liveness_template_ref','已有探针 Template ID:Build ID')))
