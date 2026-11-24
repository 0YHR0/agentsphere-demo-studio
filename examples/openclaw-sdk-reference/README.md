# 华为云 AgentSphere + 官方 OpenClaw：E2B SDK 示例

本目录可以单独复制给同事，无需安装演示网站或引用 `studio` 模块。脚本从环境变量读取凭据，不内置 API Key、沙箱令牌或 Docker 登录凭据。

提供两种入口：

1. **已有模板**：指定 ready 的 `templateID:buildID`，创建新沙箱并执行命令。
2. **完整构建**：指定镜像和 Agent Gateway，创建模板、提交 Build、输出状态与日志，ready 后创建沙箱并执行命令。

两个入口都会执行：root 用户命令 → connect 同一运行中的沙箱 → 再次执行命令 → 查询 OpenClaw 版本 → node 用户命令。任何一步失败，进程退出码为 1。

## 1. 安装锁定版本

Python 3.10+，推荐 3.11/3.12。在当前目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe demo.py --check
```

Linux/macOS 对应使用 `.venv/bin/python`。

版本固定为 E2B `2.42.0`、e2b-code-interpreter `2.9.1`、华为文档提供的 agentsphere-e2b-patch `0.2.0`，与项目根目录一致。脚本先导入 patch，再导入 E2B，版本不符直接退出。wheel URL 附有已核验的 SHA-256。

[AgentSphere 官方 SDK 文档](https://support.huaweicloud.com/sdkreference-agentsphere/agentsphere_05_0001.html)

## 2. 配置连接

先在控制台创建 Agent Gateway、获取对应区域 API Key。模板关联的网关与填写的公网域名必须匹配，并具备相应权限。API 地址、网关和模板需要属于同一区域。

PowerShell（下面的密码输入不会把密钥字面量写进命令历史）：

```powershell
$sdkSecret = Read-Host 'AgentSphere E2B API Key' -AsSecureString
$env:E2B_API_KEY = [System.Net.NetworkCredential]::new('', $sdkSecret).Password
$env:AGENTSPHERE_API_URL = 'https://agentsandbox.cn-southwest-2.myhuaweicloud.com'
$env:AGENTSPHERE_GATEWAY_URL = 'https://你的网关公网域名'
```

Linux/macOS Bash：

```bash
read -rs -p 'AgentSphere E2B API Key: ' E2B_API_KEY; echo
export E2B_API_KEY
export AGENTSPHERE_API_URL='https://agentsandbox.cn-southwest-2.myhuaweicloud.com'
export AGENTSPHERE_GATEWAY_URL='https://你的网关公网域名'
```

无需自己获取或填写 envdAccessToken / trafficAccessToken，SDK 负责处理。`X-API-Key` 同时作为网关附加请求头传入。

## 3A. 已有模板：最快验证

```powershell
.\.venv\Scripts\python.exe demo.py --template-ref '你的templateID:你的buildID' --report result.json
```

这里填你自己账号下已构建完成、且关联上述网关的官方 OpenClaw 模板。每次运行都会创建一个新沙箱，不依赖之前测试的沙箱仍然存活。

核心 SDK 调用对应代码如下，实际脚本还会校验退出码并记录时间：

```python
import agentsphere_e2b_patch  # 必须先导入
from e2b import Sandbox

options = {
    "api_key": api_key,
    "api_url": api_url,
    "sandbox_url": gateway_url,
    "headers": {"X-API-Key": api_key},
    "request_timeout": 45,
}
sandbox = Sandbox.create(
    "templateID:buildID", timeout=3600,
    lifecycle={"on_timeout": "kill"}, **options,
)
result = sandbox.commands.run(
    "echo official-openclaw-sdk-ok; id; pwd; node --version",
    user="root", cwd="/app", timeout=90, request_timeout=110,
)
print(result.exit_code, result.stdout, result.stderr)

original_id = sandbox.sandbox_id
sandbox = sandbox.connect(timeout=3600, **options)
assert sandbox.sandbox_id == original_id
result = sandbox.commands.run(
    "id; node /app/openclaw.mjs --version",
    user="node", cwd="/app", timeout=90, request_timeout=110,
)
print(result.exit_code, result.stdout, result.stderr)
```

## 3B. 创建模板并构建

先把官方镜像同步到构建器可访问的镜像仓库。官方源为 `ghcr.io/openclaw/openclaw`，也有官方 Docker Hub 镜像 `openclaw/openclaw`，参见 [OpenClaw Docker 文档](https://docs.openclaw.ai/install/docker)。本次云端直接拉 GHCR/Docker Hub 失败，改用 SWR 中原样同步且摘要一致的镜像才成功。脚本不执行镜像同步和 Docker 登录。

```powershell
$env:AGENTSPHERE_GATEWAY_ID = '你的AgentGatewayID'
$env:AGENTSPHERE_IMAGE = '你的SWR仓库/组织/openclaw-official@sha256:实际镜像摘要'
.\.venv\Scripts\python.exe demo.py --build --build-wait 2400 --report result.json
```

必须使用含 `/app/openclaw.mjs`、`node` 用户、Node.js 和 curl 的兼容官方镜像；建议选用下文的已验证版本，并以 digest 锁定镜像。构建器必须拥有拉取权限，`docker login` 本身不等于云端构建器有权拉取任意私有仓库。

模板规格为 x86_64、2 vCPU、8192 MiB 内存。Build 请求与成功验证一致：

```json
{
  "fromImage": "替换为AGENTSPHERE_IMAGE",
  "steps": [],
  "readyCmd": "curl -fsS --max-time 5 http://127.0.0.1:49983/health >/dev/null",
  "networkConfiguration": {"networkMode": "public"},
  "invoke": {"protocol": "HTTP", "port": 49983},
  "storageConfig": {}
}
```

没有配置 startCmd。readyCmd 检查的是自动注入的 **envd `/health`**，不是 OpenClaw 业务健康检查。本例验证 CLI / commands.run，不会启动模型任务或配置模型 API Key。

| 阶段 | SDK 调用 / 实际接口 |
| --- | --- |
| 创建模板 | SDK 生成接口 `post_v3_templates.sync_detailed` → `POST /v3/templates` |
| 提交 Build | SDK 生成接口 `post_v_2_templates_template_id_builds_build_id.sync_detailed` → `POST /v2/templates/{templateID}/builds/{buildID}` |
| 状态与日志 | `Template.get_build_status`；通过 SDK 鉴权 HTTP 客户端读取 `GET /templates/{templateID}/builds/{buildID}` 保留华为扩展字段 |
| 创建沙箱 | `Sandbox.create(templateID:buildID, ...)` |
| 执行命令 | `sandbox.commands.run(...)` |
| 连接同一沙箱 | 实例方法 `sandbox.connect(...)` |

模板创建中的 `gatewayID` / `arch` 和 Build 中的华为扩展字段使用 SDK 生成模型的 additional properties，不修改 SDK 源码。

## 4. 已成功的现场输出与边界

2026-10-30，贵阳一，官方 OpenClaw `2026.10.9`，镜像 manifest：

```text
sha256:deab8686a863c1d2255a43bb4677f4907b9af45aff340c062834d16756fd4ff8
```

真实执行结果摘要（来自已完成的现场验证；不是重新包装脚本的一次新云端运行）：

```text
root commands.run: exit_code=0
uid=0(root) gid=0(root) groups=0(root)
/app
v24.22.1

connect: same_sandbox=True
commands.run after connect: exit_code=0

node commands.run: exit_code=0
uid=1000(node) gid=1000(node) groups=1000(node)
OpenClaw 2026.10.9 (8b18b55)
```

本例没有测试 pause/resume、持久化存储、Gateway 业务就绪或真实模型生成。`connect` 是连接同一运行中的沙箱。

模板保留供后续使用；沙箱默认设置 3600 秒超时、到期删除，connect 会按传入 timeout 更新到期时间。`--timeout` 可调整时长，受平台配额和上限约束。脚本失败也不会自动删除资源，控制台输出以及 `--report` 文件会保留已创建的资源 ID，便于排错与手动清理。

运行结束后可清除当前 PowerShell 的密钥变量：

```powershell
Remove-Item Env:E2B_API_KEY
Remove-Variable sdkSecret
```

`result.json` 仅保存版本、资源 ID、测试输出和耗时，不保存连接令牌或请求头。命令固定为本例的诊断命令；如果改成打印业务配置，分享结果前请自行检查业务敏感内容。
