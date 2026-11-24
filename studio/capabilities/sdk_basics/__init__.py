from ...core.registry import DemoPackage,Field
from .workflow import prepare,execute,validate,build_options


METHODS={'template_sdk_build':'build_template_async','build_delete':'delete_build','sandbox_info':'sdk_info',
    'sandbox_metrics':'sdk_metrics','sandbox_timeout':'sdk_timeout','sandbox_envs':'sdk_envs',
    'file_directory':'file_directory','file_manage':'file_manage','file_batch_stream':'file_batch_stream',
    'file_urls':'file_urls','command_stream':'command_stream','command_timeout':'command_timeout',
    'process_background':'process_background','pty_session':'pty_session','sdk_basics_cleanup':'delete_sandbox'}


def source(case):
    import inspect
    from ...sdk import SDK
    return inspect.getsource(getattr(SDK,METHODS[case]))


def plan(engine,case):
    steps=['使用本工具专用实例；没有则从配置的Ready模板创建并记录归属','执行官网SDK方法并核对实际返回','不修改其他场景实例，完成后可单独回收']
    if case=='template_sdk_build':steps=['核对镜像与构建参数','Template.build_in_background异步创建模板及快照','先登记创建回调中的资源，再继续提交Build；无需等待构建完成']
    if case=='build_delete':steps=['核对本工具新建快照的归属及当前引用','Template.delete_build仅删除该Build','查询该Build确认404；模板容器由清理步骤回收']
    return {'steps':steps}


CASES=(
 ('template_sdk_build','SDK 异步构建模板','模板','用官网Template.build_in_background创建模板并异步构建，支持官网扩展参数。','sdk_basics','真实Template ID、Build ID与构建受理结果'),
 ('build_delete','删除指定 Build 快照','模板','用官网patch提供的Template.delete_build删除本工具快照，核对404。','sdk_basics','仅删除本工具新建Build'),
 ('sandbox_info','实例详情与运行检查','沙箱','调用get_info和is_running，核对实例ID及状态。','sdk_basics','get_info同一ID且is_running=True'),
 ('sandbox_metrics','查看实例指标','沙箱','按官网通过envd /metrics读取CPU、内存、缓存和磁盘。','sdk_basics','返回七项实际监控字段'),
 ('sandbox_timeout','修改沙箱有效期','沙箱','set_timeout后直接查询到期时间，避免再次connect重置TTL。','sdk_basics','到期时间与请求的秒数一致'),
 ('sandbox_envs','创建时注入环境变量','沙箱','专用实例以envs创建，在实例内读取并核对演示变量。','sdk_basics','创建参数与实际环境变量一致'),
 ('file_directory','目录与文件属性','文件','递归建目录、列目录、检查存在性并获取文件大小。','sdk_basics','make_dir/list/exists/get_info均验证'),
 ('file_manage','重命名与删除文件','文件','对本工具临时目录执行文件/目录重命名及删除，不操作其他路径。','sdk_basics','旧路径消失、新内容一致，删除后不存在'),
 ('file_batch_stream','批量写入与流式读取','文件','write_files批量写入，按stream读取二进制并核对SHA256。','sdk_basics','字节和SHA256一致'),
 ('file_urls','临时上传下载链接','文件','生成签名URL并实际上传下载，携带网关鉴权，完整URL不导出。','sdk_basics','HTTP成功且下载字节一致'),
 ('command_stream','命令回调与临时环境变量','执行','用stdout/stderr回调展示实际输出，并验证命令级envs不污染后续命令。','sdk_basics','回调与返回一致，命令变量随后不存在'),
 ('command_timeout','命令执行超时','执行','让测试命令超时，并检查对应PID已退出；不把网络超时当作通过。','sdk_basics','观察到超时且测试进程已终止'),
 ('process_background','后台进程管理','执行','启动本工具进程，列出、按PID重连并终止，检查PID消失。','sdk_basics','创建/list/connect/kill均验证'),
 ('pty_session','交互式 PTY 终端','执行','创建、调整尺寸、重连、发送输入和等待退出，再单独验证kill。','sdk_basics','实际TTY、输出、窗口尺寸及退出码正确'),
 ('sdk_basics_cleanup','回收 SDK 测试资源','清理','仅回收这组能力创建的专用沙箱与模板，保留其他场景资源。','sdk_basics','本组资源删除后404'),
)
COMMON=('extra_template_ref',)
DEFINITION=DemoPackage(id='sdk_basics',title='官网 SDK 补充能力',kind='capability',
 description='按AgentSphere官方SDK文档补齐模板、文件、命令、指标与PTY能力。',cases=CASES,
 prepare=prepare,execute=execute,source=source,plan=plan,validate=validate,
 resource_state_keys={k:('' if k in ('template_sdk_build','build_delete','sdk_basics_cleanup') else 'sdk_basics_sandbox') for k in METHODS},
 execution_cases=tuple(k for k in METHODS if k not in ('template_sdk_build','build_delete','sandbox_info','sandbox_metrics','sandbox_timeout','sdk_basics_cleanup')),
 fields=(Field('extra_template_ref','本组 Ready Template ID:Build ID',help='可选，留空使用环境配置中的模板；命令测试需要Python 3和bash'),
    Field('extra_timeout_seconds','新的有效期 / 秒','600','number','60–86400；从set_timeout请求起计算'),
    Field('extra_build_options_json','官网构建扩展 JSON',kind='secret',help='可选；snake_case参数，如env_vars、network_configuration、storage_config、liveness_probe；仅本机保存，不回读。镜像、启动命令和规格沿用环境配置')),
 case_fields={k:(('extra_build_options_json',) if k=='template_sdk_build' else ('extra_timeout_seconds',)+COMMON if k=='sandbox_timeout' else () if k in ('build_delete','sdk_basics_cleanup') else COMMON) for k in METHODS})
