# OBS 持久化存储演示

在“基础能力 → 存储”选择：挂载与读写、跨沙箱持久化、只读挂载、回收测试资源。可直接从任意验证项开始，工具会先准备独立测试文件。

## 客户需要准备什么

- 已有 OBS 桶，以及允许访问该桶的运行时委托。
- 已 Ready 的固定 `Template ID:Build ID`。Build 的 `networkConfiguration.networkMode` 为 `private`，包含项目、VPC、子网；`agencies.runtimeAgency` 指向存储委托。
- VPC 内配置访问 OBS 的终端节点。新构建从 SWR 拉镜像时还需 SWR 网络可达；只有 OBS 终端节点不足以证明 SWR 可达。
- 镜像包含 Python 3。本工具通过 `/proc/self/mountinfo` 检查实际挂载，再执行验证，不把普通目录读写视作 OBS 成功。

页面只填写固定构建、桶名和可选的桶内已有路径。**不需要填写账号 AK/SK**；挂载由 AgentSphere 使用 Build 的运行时委托鉴权。AgentSphere API Key 继续只保存在本机连接配置。

桶内路径留空表示挂载桶根目录；填写子路径时，该路径必须已存在。实测不存在的路径会在创建沙箱时返回 HTTP 400。每轮测试在挂载下生成随机 `run-...` 目录，其他对象不参与验证或清理。

## 对应 SDK

SDK 版本和 patch 与项目的 `sdk-versions.json`、`requirements.lock` 一致。先导入官方 patch，再导入 E2B：

```python
import json
import os
import agentsphere_e2b_patch
from e2b import Sandbox

metadata = {
    "agentsandbox.storage.obs": json.dumps({"obsMounts": [{
        "bucket": os.environ["OBS_BUCKET"],
        "bucketPath": "",  # 留空挂载桶根目录；子路径须已存在
        "mountDir": "/mnt/agentsphere-obs",
        "readOnly": False,
    }]})
}
sandbox = Sandbox.create(
    template=os.environ["E2B_TEMPLATE_REF"],  # Template ID:Build ID
    api_key=os.environ["E2B_API_KEY"],
    api_url=os.environ["E2B_API_URL"],
    sandbox_url=os.environ["E2B_SANDBOX_URL"],
    headers={"X-API-Key": os.environ["E2B_API_KEY"]},
    metadata=metadata,
    timeout=600,
)
# 保存 sandbox.sandbox_id 后，执行 files.make_dir/write/read；演示页面展示实际调用源码。
```

挂载与持久化使用官网 E2B SDK，不在沙箱里安装 OBS SDK 或注入账号密钥。独立 OBS API 检查仅用于本轮验收，使用用户本地凭据文件，不是运行演示的额外依赖。

## 2026-11-24 云端验收

使用客户账号中实际存在的贵阳一 OBS 桶及已有 Ready VPC/OpenClaw 模板。保留此前的 Python 和 OpenClaw 模板，没有修改客户 IAM 策略或网络配置。

| 用例 | 调用与实际证据 | 结果 |
|---|---|---|
| OBS 挂载与读写 | `Sandbox.create(metadata=...)`；`files.make_dir/write/read`；实际文件系统 `fuse.obsfs`，内容与 SHA256 一致；本机 OBS API 读取同一对象 HTTP 200 | PASS |
| 跨沙箱持久化 | 删除原实例并查询确认 404；按相同桶路径新建不同 ID 的实例；只读回原文件、不重新写入；本机 OBS API 再读 HTTP 200 | PASS |
| 只读挂载 | 另建 `readOnly=true` 实例；原文件读回一致；以 root 写入新文件被拒绝，且目标文件不存在 | PASS |
| 资源回收 | 只删除本轮命名文件，再以 `rmdir` 删除空目录；删除本轮自有实例；OBS 对象查询 404，独立列举测试前缀无残留对象 | PASS |

回收不会删除客户桶或 Ready 模板。如果测试目录中出现了额外对象，保留这些对象及目录，不递归删除。跨实例校验丢失文件时记录失败，不会重新写入文件来制造通过。

本轮新建 VPC Python 模板的构建曾因 SWR 内网请求超时而失败，未将其描述为构建成功；已删除该失败模板，改用已有 Ready VPC 模板完成上述存储验证。测试实例和测试对象已清理，页面保留客户本机连接配置，不向源码包写入桶名、资源 ID 或凭据。

[官网存储管理](https://support.huaweicloud.com/sdkreference-agentsphere/zh-cn_topic_0000002810793877.html) · [官网模板管理](https://support.huaweicloud.com/sdkreference-agentsphere/agentsphere_05_0007.html)
