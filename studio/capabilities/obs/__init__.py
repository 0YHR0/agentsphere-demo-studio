from ...core.registry import DemoPackage,Field
from .workflow import prepare,execute,validate


def source(case):
    import inspect
    from ...sdk import SDK
    from . import workflow
    methods=(SDK.create_obs_sandbox,SDK.obs_mount_info,workflow.create,workflow.seed,workflow.execute)
    if case=='obs_cleanup':methods+=(workflow.cleanup,)
    if case=='obs_readonly':methods+=(SDK.obs_readonly_check,)
    return '\n\n'.join(inspect.getsource(m) for m in methods)


def plan(engine,case):
    return {'steps':['核对固定Ready Build的VPC出站和runtimeAgency；桶及OBS终端节点由客户预先准备',
        '使用本轮独立桶路径，通过Sandbox.create(metadata=...)挂载OBS；AK/SK不传入沙箱',
        '核对真实挂载，再执行读写、跨实例保留或只读校验；清理仅删除本轮自有测试文件和沙箱']}


CASES=(
 ('obs_write','OBS 挂载与文件读写','存储','在独立桶路径挂载OBS，核对真实FUSE挂载后写入并读回文件。','obs','真实挂载、内容与SHA256一致'),
 ('obs_persist','OBS 跨沙箱持久化','存储','删除写入沙箱，以相同桶路径创建新沙箱，读回原文件。','obs','原沙箱404，新Sandbox ID与原文件一致'),
 ('obs_readonly','OBS 只读挂载','存储','创建readOnly=true实例，读回文件并验证写入被文件系统拒绝。','obs','读取一致、写入被拒绝且文件不存在'),
 ('obs_cleanup','回收 OBS 测试资源','存储','删除本轮独立路径中的测试文件和自有沙箱，保留桶与客户模板。','obs','测试文件删除且本轮沙箱404'),
)
DEFINITION=DemoPackage(id='obs',title='OBS 持久化存储',kind='capability',
 description='官网metadata挂载方式；通过构建委托授权，演示无需填写AK/SK。',cases=CASES,
 prepare=prepare,execute=execute,validate=validate,source=source,plan=plan,
 resource_state_keys={c[0]:'obs_sandbox' for c in CASES},
 fields=(Field('obs_template_ref','OBS Ready Template ID:Build ID',help='必须是VPC出站且配置runtimeAgency的固定Ready构建，镜像需含Python 3'),
    Field('obs_bucket','OBS 桶名',help='填写实际桶名；须已通过委托授权且VPC内OBS终端节点可达'),
    Field('obs_prefix','桶内已有路径（可选）',help='留空挂载桶根目录；子路径必须已存在。工具仅在挂载下新建随机run目录，不改动其他对象')),
 case_fields={c[0]:(() if c[0]=='obs_cleanup' else ('obs_template_ref','obs_bucket','obs_prefix')) for c in CASES})
