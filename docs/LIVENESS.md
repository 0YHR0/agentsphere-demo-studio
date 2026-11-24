# AgentSphere 原生存活探针验证

`readyCmd` 用于等待就绪；`livenessProbe` 是华为云 AgentSphere 的构建扩展字段，需要单独传入。官网固定版本的 E2B SDK 和 patch 保持不变，工具通过生成模型的 `additional_properties` 发送扩展，Build 详情通过 SDK 已鉴权 HTTP client 读取。

## 配置自己的业务探针

在环境配置第三步选择现场构建，展开“运行期存活探针”，填写 JSON。HTTP / Exec 二选一。

```json
{
  "invoke": {"protocol": "HTTP", "port": 18789},
  "livenessProbe": {
    "probeHandler": {"httpGet": {"path": "/health"}},
    "probeConfig": {"enabled": true, "initialDelaySeconds": 5,
      "timeoutSeconds": 3, "periodSeconds": 10, "failureThreshold": 3}
  }
}
```

端口和 path 必须对应实际业务，HTTP protocol / port 省略时由服务端继承 invoke。只有 enabled=true 且有 handler 才启用。Exec command 使用完整参数数组，最多 20 项，每项最多 4096 UTF-8 字节。readyCmd 不能替代 livenessProbe。

保存配置后，在“构建 OpenClaw 模板”中提交 Build。在“查看 Build 状态与日志”中核对服务端回显的 invoke / livenessProbe。

## 独立故障演示

选择“存活探针与故障检测”，填入有权拉取且包含 Python 3、base64 的测试镜像，或本工具生成的专用模板引用。首次构建可能需要数分钟。

- 仅准备状态：准备专用模板、启用原生 HTTP 探针并创建独立沙箱。
- 准备并演示：先观察 20 秒健康基线，再注入 HTTP 503，观察最多 180 秒。日志和结果分别记录异常状态、错误信息、连接失败及服务身份变化。
- 本步骤不会向当前业务沙箱注入故障，不会替换当前业务 Sandbox ID。资源会加入本工具清理范围。

“探针发现故障”“业务进程重启”“整个沙箱恢复”是不同结果。工具仅在真实检测到 Error 或业务身份变化并恢复 HTTP 200 时判定观察成功，不会将 Error 写成自动重启成功。

## 2026-10-20 贵阳一实测

使用用户自己的账号完成 HTTP 探针测试：Build 请求接受扩展，Build 详情回显了从 invoke 继承的 HTTP 协议和端口。开启后先健康运行约一分钟，访问日志记录到 `nacre-agent-probe` 的持续探测。

随后分别注入 HTTP 503、终止 startCmd 业务进程，两次都出现数据面 `Session not found`，最终控制面显示 `state=paused`、`detailedState=Error`、`errorMessage=sandbox abnormal deleted`。未观察到业务自动重启。四个反例（handler 空、HTTP/Exec 同传、path 非绝对、Exec command 空）均由服务端返回 400。

这些结果表明当前接入支持原生故障探测，不能据此承诺 K8s 式自动重启。Exec 的有效载荷在工具中做语法校验并提供示例；本轮正向故障实测使用 HTTP。
