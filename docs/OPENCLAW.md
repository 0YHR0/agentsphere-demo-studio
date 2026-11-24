# OpenClaw 项目交付助手

## 准备镜像

参考 [OpenClaw Docker 文档](https://docs.openclaw.ai/install/docker)。官方文档提供 `ghcr.io/openclaw/openclaw` 镜像来源，建议为演示固定一个经过验证的 release tag 或 digest，再按客户要求同步到自己的 SWR。

AgentSphere 的具体镜像要求、架构、用户、启动命令以对应版本的华为云文档和镜像说明为准。本项目不会把开发者私有镜像写成客户默认值，也不会凭猜测安装或替换 envd。

最便捷的演示方式是先在客户控制台完成一个可用的 OpenClaw 模板，再把其 Ready Template ID 填入配置。构建演示可以单独使用客户有权限拉取的同一镜像。

## 场景入口与准备

“基础能力”提供 17 项独立 SDK 能力，可以从任意能力开始准备状态。“OpenClaw 场景”是独立的 8 步业务演示，创建自己的沙箱，不复用基础能力的实例。

进入 OpenClaw 场景后，先阅读业务目标、输入和输出，填写并保存：

- 云环境：在环境配置中填写 AgentSphere API Key、API 地址和 Gateway，选择包含 OpenClaw 的 Ready 模板。构建可提前在基础能力中完成。
- 运行环境：镜像中实际存在的 CLI（如 `openclaw`）和运行用户。不同镜像的用户与安装路径可能不同。
- 模型：OpenAI 兼容 Base URL、模型 ID、模型 API Key。模型 Key 与 AgentSphere Key 不同，页面不回填已保存的 Key，留空保留原值。
- 网络：本机可以访问控制面 API、Gateway 和模型 HTTPS 服务；沙箱模板允许公网出站。Gateway 的公网入口不能证明模板已开通出站网络。

## 按业务步骤执行

1. **准备运行环境**：使用固定 Ready Build 创建专用沙箱，检查 OpenClaw CLI。
2. **验证公网访问**：从这个沙箱请求 `https://www.baidu.com`，要求 HTTP 200。
3. **上传项目简报**：以业务用户写入简报，读回比对并记录 SHA256。
4. **生成交付摘要**：读取上一步的实际输入文件，调用真实模型并保存 Markdown。每次任务使用独立输出目录，避免把旧文件当作本次产出。
5. **查看与下载交付物**：通过 SDK 读取摘要，核对 SHA256，可下载为 `delivery-summary.md`。
6. **等待人工确认**：核对简报和交付物后暂停当前实例。
7. **恢复业务现场**：connect 原 Sandbox ID，读取原简报和交付物并核对 SHA256；不会重新上传文件或补跑生成任务。
8. **结束与回收**：仅删除本场景的业务沙箱，验证详情 404。基础能力沙箱与客户已有模板保留。“演示资源”的集中清理仍会清理本工具创建的所有资源。

点击步骤只切换展示，点击“执行本业务步骤”才发起操作。后续步骤缺少资料时提示前一步，不能通过自动重写文件冒充恢复。原实例过期时明确报错；释放其记录后重新准备环境。

任务通过 `commands.run()` 调用 OpenClaw：

```bash
OPENCLAW_CONFIG_PATH=<本任务配置> OPENCLAW_STATE_DIR=<本任务状态目录> \
  openclaw agent --local --agent main --session-id <本次唯一ID> \
  --message '<读取上一步简报并写入交付摘要的指令>' --json
```

配置定义一个名为 `demo` 的 OpenAI 兼容 provider，并选择 `demo/<模型ID>`。它指向沙箱内 loopback 中转服务；真实模型 Key 仅留在本机，经 SDK 读写请求和响应后由本机发送模型 HTTPS 请求，Key 不写入沙箱。中转会把流式请求转为提供商完整响应，再包装为 SSE；每次任务最多 12 次模型调用，单次输出上限 4096 tokens。参考 [模型配置](https://docs.openclaw.ai/concepts/model-providers/custom-providers) 和 [Agent CLI](https://docs.openclaw.ai/cli/agent)。

此任务是独立的一次 Agent 运行，配置和状态路径都与镜像已有 Gateway 分开；不停止、不覆盖镜像原有的 OpenClaw 配置。没有实现模型的模拟回答，失败会显示真实错误。

Agent 只启用 read/write 工具，读取上传的项目简报，并生成 `workspace/delivery-summary.md`。工具再用 SDK 读取该文件，把真实交付摘要展示在页面上。示例工作区跳过首次身份初始化，避免出现询问姓名的演示干扰。

## 讲解边界

- SDK 文件保留用例检查同一沙箱暂停恢复后的文本和 SHA256。
- 这不代表跨实例 SFS 持久化，也不代表模型会话的业务状态已自动恢复。
- 工具没有向 IM 群、邮件或客户业务系统发送消息。
- 实际任务仅使用页面列出的虚构项目简报。模型密钥和客户数据不要放进 Build 镜像或公共仓库。
