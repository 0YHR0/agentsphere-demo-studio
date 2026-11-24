# AgentSphere Demo Studio

2026-11-24：按[官网SDK文档](docs/SDK_CAPABILITIES.md)补齐15项基础能力，并新增[OBS存储4项验证](docs/OBS.md)：挂载读写、跨沙箱持久化、只读挂载、清理；新增项目均已云端实测通过，基础能力现为36项。官方patch已按最新文档升级至0.2.0，E2B版本保持不变。代码解释器和SFS挂载仍待专用资源，不计入本轮云端PASS。

**推荐客户演示：[电商订单报表 Agent](docs/ORDER_REPORTS.md)**。日常快报、月度商品汇总、客户退款对账串起真实业务：四种报表工具 → AgentSphere执行验证 → 时间/内存reward → CPU训练 → 未参与训练文件上与固定规则对照 → 保存重载与清理。无需GPU或外部模型Key，不预设RL必须赢。CPU RL统一使用这个业务案例；现在共60项能力与场景动作。

订单报表 RL 已用 **Docker Official Python 3.12.16 / Debian 12** 镜像完成云端验证，无需小艺或OpenClaw镜像。官方镜像来源、同步客户SWR的方法及可复用Build请求见 [Python模板准备](docs/PYTHON_TEMPLATE.md) 和 `examples/python_cpu_template.json`；客户填写自己的模板和仓库地址。Miles奖励回调接入示例作为进阶集成保留。

面向解决方案工程师和客户的本地演示工具。浏览器选择能力，后端使用真实 E2B SDK 调用客户自己的华为云 AgentSphere；无需修改 Python 源码或按固定顺序演示。

2026-11-10：已完成第一阶段模块化重构。基础 SDK 能力、健康探针、OpenClaw 与 VPC 场景分别注册；客户场景页面按包元数据生成介绍、配置和步骤。开发者可复制场景模板新增能力，详见 [扩展与架构说明](docs/EXTENDING.md)。

2026-11-11：新增 [Miles RL 场景](docs/MILES_RL.md)，共 6 步：准备环境 → 生成候选 → 独立沙箱执行并评分 → 验证 Miles 奖励回调 → 导出 JSONL → 清理。可选实时模型生成或明确标注的内置正负对照；reward 来自现场测试。GPU 训练在外部 Miles 集群完成。本工具现在有 35 项能力与场景动作。

## 开始使用

需要 Python 3.10+、可访问 AgentSphere 的网络及已开通服务的华为云账号。

Windows 双击 `start.cmd`，或在 PowerShell 运行：

```powershell
.\start.ps1
```

Linux / macOS：

```bash
bash start.sh
```

启动脚本创建 `.venv`、安装固定版本依赖，然后打开 **http://127.0.0.1:8766/**。关闭终端不会删除云端资源；演示结束请先在“演示资源”中清理。

也可手动安装、启动：

```bash
python -m venv .venv
# Windows 使用 .venv\Scripts\python.exe；以下为 Linux/macOS
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m studio.server --open
```

## 首次配置

1. 打开“环境配置”。在华为云控制台手动创建 Agent Gateway，复制 **Gateway ID** 和对应 **公网域名**。网关入口与模板出站网络模式不同，不能相互替代。
2. 创建 AgentSphere API Key，填写区域、控制面 API URL、Gateway ID 和域名。不要把 IAM AK/SK 或模型 API Key 当成 AgentSphere API Key。
3. 推荐填写客户已有的 **Ready 模板 ID**。它必须关联相同 Gateway；本工具只使用、不删除该模板。这样现场不需要等待构建。
4. 要演示 Build，另填有权限拉取的镜像地址、架构和镜像对应的 startCmd/readyCmd。工具不会默认引用开发者私有镜像。
5. 保存并检查连接。版本检查与模板列表读取通过后，从“能力演示”任选一项。

详细介绍：[演示手册](docs/DEMO.md)、[OpenClaw 场景](docs/OPENCLAW.md)、[发布与数据管理](docs/RELEASE.md)。

## 按客户关注点演示

每项能力有两个按钮：

- **仅准备状态**：自动完成所需前置条件，例如创建沙箱、写文件、暂停。不会执行最后的演示动作。
- **准备并演示**：先准备状态，再执行所选 SDK 操作，展示代码、结果和过程。

例如直接选择“恢复后检查文件”：工具准备运行实例，写入简报和二进制文件，保存 SHA256，暂停并恢复**同一 Sandbox ID**，然后用 SDK 读取文件并比对。

“基础能力”提供 17 项独立 SDK 验证：连接、模板与 Build、沙箱、命令、文件、公网访问、暂停恢复、探针和清理。“OpenClaw 场景”提供独立的 8 步业务流程：先配置模型与运行环境，再准备专用沙箱 → 检查公网 → 上传简报 → 生成摘要 → 下载交付物 → 暂停 → 恢复核对 → 释放业务沙箱。没有 Timeout 演示步骤。

“客户场景”还包含 VPC HTTP / WebSocket 的 4 步流程：核对 private 出站 Build 并创建专用沙箱 → 内网 HTTP → 单连接 WebSocket 与空闲回显 → 释放本场景实例。需提前准备 VPC 模板和内网测试服务；示例服务器位于 `examples/vpc_echo_server.py`。运行记录可在资源页面导出脱敏 Markdown 报告。

直接 SDK 示例见 `examples/sdk_quickstart.py`。CLI 与页面共用注册表和引擎：`python -m studio.cli list`、`python -m studio.cli describe command`。CLI 默认使用独立 `.local/cli` 配置，避免与浏览器数据混用。

长时间 Build 与 Ready 模板运行分开。失败不会自动删除现场，也不会更换沙箱 ID 伪装恢复；可从资源面板集中清理。

## SDK 版本与官方 patch

按照 [华为云 SDK 文档](https://support.huaweicloud.com/sdkreference-agentsphere/agentsphere_05_0001.html) 的安装命令锁定：

| 组件 | 固定版本 |
|---|---|
| e2b | 2.42.0 |
| e2b-code-interpreter | 2.9.1 |
| agentsphere-e2b-patch | 0.2.0 |

patch 下载地址和 SHA256 记录在 `sdk-versions.json`；`requirements.txt` 使用带 SHA256 的官方文档下载 URL。启动脚本使用 requirements.lock 固定完整依赖集合，不会自动安装浮动最新版。启动检查版本和 `_agentsphere_e2b_patched` 标记。

显式 `import agentsphere_e2b_patch` 后才导入 E2B。没有自定义 Sandbox 子类，没有复制以前测试环境的版本替换逻辑。patch 0.2.0 来自华为云官方文档指定的 OBS 地址，负责 envd 流量令牌及模板扩展参数适配，并提供 Template.delete_build；新“SDK异步构建模板”直接调用 Template.build_in_background。保留的底层接口演示继续明确标注 SDK 生成模型/认证 HTTP 客户端。

服务进程保留 SDK 返回的 Sandbox 实例，暂停恢复使用官方实例方法 `sandbox.connect()`；每次仍发起真实连接请求。若后台重启后旧实例缺少 envdVersion，状态预制会明确记录并保留旧实例，准备一个新的自有测试实例；不会用新 ID 冒充旧实例的文件保留结果。

模板列表通过 SDK 已鉴权 HTTP 客户端读取原始 JSON，因为华为返回的 `Ready` 与原生 SDK 枚举 `ready` 不同。页面明确标注该兼容方式。Build 状态/日志使用 `Template.get_build_status()`，日志来自 `/status` 的 `logEntries`。

## 数据与资源

- 服务仅监听 `127.0.0.1`；不是多人共享的公网应用。
- 密钥保存在本机 `.local/config.json`；浏览器仅能读取“是否已配置”，不会回读密钥。修改时留空保留原值。
- `.local/session.json` 保存资源账本和脱敏执行结果，刷新/重启不会丢失本工具创建的资源 ID。
- 工具失败时保留资源。清理只操作账本中 `owned=true` 的资源；用户输入的 Ready 模板和日志模板不会加入清理范围。
- 不要共享 `.local` 或 `.venv`。发布脚本使用明确的源码白名单，拒绝常见密钥格式；不把运行目录放进 ZIP。
- 真实模型 Key 只保存在本机。沙箱中的 loopback 服务通过 SDK 文件交换请求/结果，本机后端才携带 Key 调用模型提供商；不需要公网隧道。真实云资源和模型调用可能产生费用。

## 测试和打包

```bash
python -m unittest discover -s tests -v
python scripts/package_release.py
```

产物为 `dist/agentsphere-demo-studio.zip`，适合上传到自己的公共 GitHub 仓库。上传 ZIP 解压后的源码，而不是整个开发目录。详见 [发布说明](docs/RELEASE.md)。

本工具不是华为云或 OpenClaw 官方发行物。使用者需要有相应云资源与模型调用权限。


原生存活探针的扩展参数、独立故障演示和实测边界见 [存活探针说明](docs/LIVENESS.md)。异常检测与业务自动重启分别展示。
