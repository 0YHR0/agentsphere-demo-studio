# 扩展能力与客户场景

项目采用同一执行引擎服务浏览器和 CLI。能力与场景通过 Python 包注册；新增场景无需修改 Engine、服务器分发逻辑或前端步骤表。

## 目录

```text
studio/
  core/registry.py          # DemoPackage、Field、自动发现及校验
  core/resources.py        # 资源归属、场景/运行 ID、账号指纹
  core/instrumentation.py  # 自有 SDK 适配层操作记录
  core/reporting.py        # 实际执行账本导出
  capabilities/basic/      # 模板、Build、沙箱、文件、网络、暂停恢复
  capabilities/sdk_basics/ # 官网原生模板构建、指标、文件、命令与PTY
  capabilities/obs/        # OBS挂载、跨实例持久化、只读与自有资源清理
  capabilities/health/     # 独立探针演示
  scenarios/openclaw/      # OpenClaw 完整业务流程
  scenarios/vpc/           # 私网 HTTP / WebSocket
  scenarios/miles_rl/      # 代码候选执行、主机评分与 Miles custom_rm
  scenarios/order_reports/ # 电商订单CSV、四种工具、成本奖励与留出规则对照
  engine.py                # 调度、共享资源准备、状态等待和账本
  sdk.py                   # 锁定版本 SDK + patch，华为扩展参数适配
  server.py                # 通用 HTTP API
  cli.py                   # 同一注册表与引擎的命令行入口
examples/scenario_template/ # 可复制的场景包模板
examples/sdk_quickstart.py  # 直接使用官方 SDK 的独立示例
```

SDK 及官方 patch 继续按 sdk-versions.json 锁定。本次重构没有升级 SDK 或新增运行时依赖。`studio/openclaw.py` 及 Engine.openclaw_task 仅保留为旧导入/测试集成的兼容入口，实际实现已迁入场景包。

## 新增场景

1. 把 examples/scenario_template 复制到 studio/scenarios/customer_example。
2. 替换包 ID、action ID、字段前缀及业务介绍。ID 使用小写字母、数字和下划线，所有 action/field 全局唯一。
3. 定义 Field：key、label、default、kind、help。密钥 kind=secret，默认值必须为空；不要把客户密钥或资源 ID 填进源码。下拉框使用 kind=select、choices=((值,显示名称), ...)，default 必须在 choices 中。
4. 实现 prepare、execute、plan、source，并提供 DEFINITION=DemoPackage(...)。
5. 为前置条件、关键断言、失败、隔离与清理编写测试。
6. 重启应用。注册器扫描 capabilities/ 与 scenarios/ 下含 DEFINITION 的直接子包；页面自动生成场景选项、介绍、配置及步骤。

capabilities 中的包使用 kind=capability，会显示在基础能力卡片；scenarios 中的客户包使用 kind=scenario，显示在客户场景选择器。两者均走通用表单渲染，无需修改 app.js。

## 合约

- cases：六元组列表 `(action_id, title, group, description, prerequisite_label, expected)`。
- prepare(engine, driver, case)：只准备该步骤所需状态，不把准备成功当作目标动作成功。
- execute(engine, driver, case)：执行实际操作并做断言；失败抛出异常。返回 `{"skipped": true, "reason": ...}` 时记录为 skipped。
- plan(engine, case)：返回包含 steps 的字典，解释准备过程。
- source(case)：从实际调用函数获取源代码；避免另维护一份会漂移的演示代码。
- validate(config, case, mode)：执行前检查字段，避免缺参数时先创建资源。
- validate_config(values, case)：可选的保存时组合校验，禁止在此发起云端调用。
- execute 返回值可包含 presentation.metrics（label/value 数组）及 presentation.table（columns 的 key/label、rows 数组），通用页面会显示指标卡和对比表；数据必须来自本次实际执行。
- presentation.series 可使用 label 与 points=[{x,y},...] 展示 0–1 reward 曲线；明确指标含义，不能把训练采样reward称为独立评估分数。
- fields / case_fields：字段元数据与每个 action 可保存的字段白名单。场景 config_action 指定页面保存本场景字段的 action。
- prerequisites / outcome：客户开始前需要准备的条件与最终业务交付。
- visualizer：可选客户端可视化名称。订单报表RL使用order_router；客户端在window.StudioVisuals中注册render(host,context)，读取当前场景账本绘制界面。标准场景无需该字段。新增可视化脚本需加入服务器静态资源白名单和HTML引用，不支持用户上传任意客户端代码。渲染器不供应reward，不绕过引擎执行或资源归属校验。
- recommended：可选布尔值，推荐场景在客户选择器中优先展示；不会自动调用SDK。默认推荐订单报表，原有场景ID和运行记录不改变。
- view(run)：可选只读场景视图，附加到状态快照的display字段；只聚合或校验已有记录，不调用云端、不执行训练、不修改run。订单报表用它展示基准值和经参数hash核对的逐轮概率变化。
- resource_state_keys：可选的action到会话字段名映射，工作台用该字段解析本组Sandbox，避免显示其他能力的实例。空字符串表示该动作没有Sandbox上下文；未设置则沿用默认行为。SDK补充能力使用sdk_basics_sandbox。

注册模块应保持轻量；SDK、场景业务模块在 hook 内导入，避免配置、注册器和执行引擎循环导入。自定义 hook 是本机可信源代码，不支持通过浏览器上传或执行不可信插件。

## 状态与资源

用 `engine.bind_scenario(package_id, run)` 创建/更新场景上下文；通过 `engine.scenario_run(package_id)` 读取。运行具有独立 run_id，记录在 `session.json` 的 scenario_runs 中。

云端创建成功后必须先登记资源，再做后续操作：

```python
sid = driver.create_sandbox(template_ref)
run = engine.bind_scenario('my_scene', {'sandbox_id': sid})
resource = dict(sandbox_id=sid, template_id=template_ref.split(':')[0],
                template_ref=template_ref, owned=True, state='creating')
engine.ledger.record('sandbox', resource, 'my_scene', run['run_id'])
engine.save()
engine.wait_state(driver, resource, 'running')
```

资源带 scope、run_id、账号指纹、区域和 Gateway。清理前 `engine.own(...)` 核对账本及账号；不登记客户提供的 Ready 模板为 owned。失去原实例或哈希不一致时必须失败，不能创建替代实例、重写文件后宣称恢复成功。

状态等待优先判断 detailedState。Error 立即失败；粗粒度 state=paused 但详细仍为 Pausing 时继续等待。兼容测试驱动/旧响应缺少 detailedState 时，才使用粗粒度状态。

旧 session.json 的资源列表与 OpenClaw 上下文仍可读取；没有做云端迁移或删除。账号指纹不存在的旧资源沿用原有归属检查。旧记录无法补造历史 HTTP 状态码或请求数据。

## 日志与报告

运行结果、事件、适配器操作、耗时及实际捕获的控制面 HTTP 响应会写入 jobs。操作记录最多保留最近 200 条；文件读写正文不复制到操作日志。后台进程句柄仅记录 PID。

`layer=sdk_adapter` 是适配层调用结果，不能当成原始 HTTP 返回；`layer=http` 才包含已实际捕获的响应码。某些高层 SDK 调用的内部 HTTP 并未被截获，不能据返回值补造状态码。准备、正式执行、失败、中断和跳过保留各自含义。

页面资源区可导出 Markdown；`GET /api/report` 返回结构化记录，`GET /api/report.md` 下载 Markdown。配置中声明的密钥值、鉴权 Header、Cookie 和完整 PEM 私钥会脱敏。分享结果前仍应核对业务文件内容是否适合客户传播。

## CLI 与直接 SDK

```bash
python -m studio.cli list
python -m studio.cli describe vpc_http
python -m studio.cli --data-dir .local/cli run vpc_http --prepare
python -m studio.cli --data-dir .local/cli run vpc_http
python -m studio.cli --data-dir .local/cli report --format markdown
```

list/describe 不访问云端。run 调用真实 SDK，需要对应目录 config.json 已完成配置。CLI 默认独立 `.local/cli`，浏览器默认 `.local`；可通过服务器 --data-dir 为该配置目录提供环境设置页面。不要用两个进程同时写同一个数据目录。

独立 SDK 示例 `examples/sdk_quickstart.py` 使用 E2B_API_KEY、E2B_API_URL、E2B_SANDBOX_URL、AGENTSPHERE_TEMPLATE_REF 环境变量。它不使用 Studio 资源账本；成功后删除自己创建的实例，失败时输出 ID 并保留现场。

## VPC 场景

用户提前构建 private 出站模板。页面填写固定 Template ID:Build ID；工具核对 Build 的 networkConfiguration 后创建专用沙箱。用户准备 ECS 服务及安全组，本阶段不自动购买 ECS、创建 Gateway 或自动构建 VPC 模板。

可在 VPC 内服务器启动依赖 Python 3 标准库的测试服务：

```bash
python3 examples/vpc_echo_server.py --bind 0.0.0.0 --port 8080
```

沙箱镜像需要 curl 与 Python 3。填写 ECS 私网 IPv4 的 `/health` 与 `/ws`，不使用公网管理地址。目标目前限定 RFC1918 IPv4 字面值，不支持私有域名、业务鉴权或 WebSocket 子协议；这些可在后续场景中扩展。

HTTP 从沙箱执行 curl，显式绕过代理，要求2xx并记录正文、远端 IP、总耗时。WebSocket 使用标准库客户端，校验101及accept，单连接、不重连、文本回显一致；空闲区间不发应用消息，但会响应服务端ping。默认观察30秒/空闲10秒，可改20–600秒，空闲至少5秒并留足收发时间。仅准备状态不会启动长连接测试。

本次工程回归验证了本地协议与场景调度；没有重新使用客户账号进行云端VPC实测。历史2026-10-22云端通过记录是另一轮测试，不能替代本次配置的现场结果。
