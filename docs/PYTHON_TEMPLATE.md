# 官方 Python 沙箱模板准备

订单报表 RL 使用 Linux、Python 3、SQLite 和 resource 标准库，无需小艺、OpenClaw、GPU 或模型 API Key。运行用户默认 sandbox，必须存在并可写 /tmp。

## 镜像来源

已验证 Docker Official Image 的 Python 3.12 Debian Bookworm slim 版本：

```text
docker.io/library/python:3.12-slim-bookworm
public.ecr.aws/docker/library/python:3.12-slim-bookworm
```

官方来源：[Docker Hub Python](https://hub.docker.com/_/python)、[Docker 在 ECR 的 Python 仓库](https://gallery.ecr.aws/docker/library/python)。这是 Docker 社区维护的 Docker Official Image。tag 会更新，可在确认兼容后固定镜像 digest。

本区域2026-11-20实测：云端拉取Docker Hub连接被重置，ECR Public token请求返回DENIED；本机读取官方ECR源成功。因此推荐在客户可访问官方源的环境，将linux/amd64镜像按摘要同步至自己的SWR，并核对源/目标manifest及各层摘要一致，再使用自己的SWR地址构建。

## 创建与构建

1. 在环境配置中填写自己的 Agent Gateway 和 API Key。
2. 创建 x86_64、2 CPU、2048MiB 模板；本区域当时实测最低内存为2GiB。
3. 使用 [Build 请求体](../examples/python_cpu_template.json)，将 fromImage 改为自己可访问的镜像地址或摘要。示例不包含开发者的私有SWR、模板ID或凭据，官方ECR源固定到已验证的linux/amd64摘要。
4. 用锁定版本的官网SDK及官方patch，通过 `SDK.submit_build(resource, build_options)` 提交构建。
5. Ready后将自己的 `Template ID:Build ID` 填入订单报表场景配置，执行“准备报表环境”验证。

该区域当时的构建接口只接受USER步骤，拒绝RUN。示例以root初始化：startCmd创建sandbox用户后执行sleep infinity；readyCmd确认用户存在且Python标准库可用。业务测量通过SDK明确以sandbox用户执行，不把root初始化当作sandbox用户启动。

官方Python镜像不包含envd，由AgentSphere构建阶段注入。2026-11-23订单报表场景已用Python 3.12.16 / Debian 12、sandbox用户uid=1000完成两轮真实验证。模板仍需在客户自己的区域完成“创建沙箱并执行命令”检查；官方镜像地址不保证任意区域都可直接拉取。

此模板只提供Python执行环境，OpenClaw演示需要另外准备包含OpenClaw的模板。
