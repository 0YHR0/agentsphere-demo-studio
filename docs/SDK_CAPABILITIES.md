# 官网 SDK 基础能力覆盖

2026-11-24通过浏览器核对AgentSphere SDK文档。SDK版本保持e2b 2.42.0、e2b-code-interpreter 2.9.1，patch更新为官网OBS提供的0.2.0，SHA256由sdk-versions.json固定。无SDK源码修改或额外自定义patch。

## 新增的15项演示

在“基础能力”中按模板、沙箱、文件、执行和清理分类选择；无需依次运行。新能力使用独立登记的测试实例，支持单独指定Ready模板和执行用户/工作目录。“仅准备状态”不执行最终验证。

| 演示 | 官网 SDK 方法 | 本轮云端结果 |
|---|---|---|
| SDK异步构建模板 | Template.build_in_background | PASS：Ready，创建实例并执行命令成功 |
| 删除指定Build快照 | Template.delete_build | PASS：该Build查询404 |
| 实例详情与运行检查 | get_info / is_running | PASS：同一实例ID，运行状态True |
| 查看实例指标 | sandbox._envd_api.get('/metrics') | PASS：CPU、内存、缓存、磁盘7项字段 |
| 修改沙箱有效期 | set_timeout | PASS：直接查询到期时间与请求一致 |
| 创建时注入环境变量 | Sandbox.create(envs=...) | PASS：实例内读取一致 |
| 目录与文件属性 | files.make_dir/list/exists/get_info | PASS：目录、缺失路径及文件大小核对 |
| 重命名与删除文件 | files.rename/remove | PASS：文件、目录重命名及递归删除 |
| 批量写入与流式读取 | files.write_files / files.read(format='stream') | PASS：二进制字节与SHA256一致 |
| 临时上传下载链接 | upload_url / download_url | PASS：实际HTTP上传下载，字节一致 |
| 命令回调与临时环境变量 | commands.run(on_stdout,on_stderr,envs) | PASS：回调/返回一致，变量不污染后续命令 |
| 命令执行超时 | commands.run(timeout=...) | PASS：观察到超时，目标PID已退出 |
| 后台进程管理 | commands.run(background=True)/list/connect/kill | PASS：同PID重连，终止后不在列表 |
| 交互式PTY终端 | pty.create/send_stdin/resize/connect/kill、handle.wait | PASS：真实TTY、40×120尺寸、计算输出与退出码核对 |
| 回收SDK测试资源 | Sandbox.kill、模板删除 | PASS：本组资源404，其他资源保留 |

此前模板创建/列表、Build状态与日志、沙箱创建/列表、命令执行、文件读写/上传下载、公网访问、暂停/恢复及文件保留、沙箱/模板删除和健康探针继续保留。后续新增[OBS存储4项](OBS.md)，均已云端实测PASS；基础能力共36项，含场景的项目总动作数为60。

## 官网原生构建参数

“SDK异步构建模板”的镜像、CPU、内存、启动及就绪命令沿用环境配置；可以在该步骤的“官网构建扩展JSON”填写snake_case参数。该字段只保存在本机且不回读，不将扩展值复制到SDK操作摘要。

可用示例见[扩展参数JSON](../examples/sdk_template_extensions.json)。支持network_configuration、invoke、env_vars、first_invoke_cmd、agencies、liveness_probe、observability、session_storage_config、storage_config、tags、skip_cache、description；api_headers仅允许X-Project-ID，鉴权始终使用本机API Key。

初轮构建验证了公网网络、invoke、env_vars和first_invoke_cmd的参数回显；env_vars还在启动进程中核对成功。first_invoke_cmd仅确认被服务端保存，本轮没有将envd命令请求当作业务invoke来宣称它已执行。后续已用客户资源验证OBS挂载及运行时委托，详见[OBS实测说明](OBS.md)；SFS和日志采集未纳入本轮云端验收。

SDK创建回调一拿到Template/Build ID就登记归属，即使后续提交失败，资源也保留在清理账本。删除Build前检查当前实例引用；只允许删除本工具创建的快照，不删除客户提供的Ready模板。删Build和删模板容器是不同步骤。

## 实测发现与边界

- 官方Python镜像没有SDK默认的/home/user目录。新增命令和PTY显式使用配置的cwd；可使用/或/tmp。
- Build的env_vars注入启动进程；新开SDK命令没有自动继承该变量。创建实例envs和命令级envs分别实测通过，展示时明确区分三种作用范围。
- set_timeout验证后不再connect，否则connect会按配置重置TTL。该演示验证有效期修改，不是到期后自动暂停/删除测试。
- URL需要Agent Gateway路由/鉴权头，示例通过SDK的envd客户端实际请求；不将其描述为无需鉴权的公开链接，导出记录省略签名URL。
- 进程被SDK kill后，此环境返回退出码-1；只有kill确认成功且PID从列表消失，才视为终止通过。
- 初始失败和修复记录保留在本机测试账本。最终15项全部PASS，测试资源回收；源码发布包没有密钥、私有资源ID或历史运行账本。

## 本轮未纳入云端验收

OBS在提供桶后已补测通过；以下能力仍未纳入本轮云端验收：

| 能力 | 需要的资源 |
|---|---|
| run_code代码解释器 | 预装代码执行环境的code-interpreter模板；官网要求49999端口HTTP /health，普通Python镜像不能直接替代 |
| SFS持久化挂载 | 已有可测试的SFS Turbo、VPC模式模板、网络及委托 |

## 对照的官方文档

- [SDK安装与patch](https://support.huaweicloud.com/sdkreference-agentsphere/agentsphere_05_0001.html)
- [模板及快照管理](https://support.huaweicloud.com/sdkreference-agentsphere/agentsphere_05_0007.html)
- [实例管理](https://support.huaweicloud.com/sdkreference-agentsphere/agentsphere_05_0002.html)
- [文件操作](https://support.huaweicloud.com/sdkreference-agentsphere/agentsphere_05_0003.html)
- [执行命令](https://support.huaweicloud.com/sdkreference-agentsphere/agentsphere_05_0004.html)
- [进程/PTY管理](https://support.huaweicloud.com/sdkreference-agentsphere/agentsphere_05_0006.html)
- [运行代码](https://support.huaweicloud.com/sdkreference-agentsphere/agentsphere_05_0005.html)
- [存储管理](https://support.huaweicloud.com/sdkreference-agentsphere/zh-cn_topic_0000002810793877.html)
