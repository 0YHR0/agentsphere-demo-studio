# 公共仓库发布

源码项目与历史测试项目放在不同目录。不要复制旧测试项目中的 `.env`、reports、JSON 状态、截图或私有镜像配置。

运行：

```bash
python -m unittest discover -s tests -v
python scripts/package_release.py
```

发布脚本只收集顶层发布文件和 studio、web、docs、tests、scripts 目录内明确允许的源码扩展名；跳过缓存、虚拟环境、运行状态与 dist。还会扫描常见凭据格式和本机私有配置中实际存在的密钥值。

将生成 ZIP 解压到新目录，再创建自己的 GitHub 仓库。建议先查看文件清单，再执行 Git 初始化和提交。不要对开发目录直接无检查地 `git add .`。

公开仓库只提交上述白名单文件，从干净导出目录初始化 Git，不包含开发目录的历史提交、本机身份邮箱或运行记录。后续更新也应先重新打包、检查，再同步源码文件。许可证采用 MIT；官网 patch 通过原始 URL 安装，版本和 SHA256 都在 sdk-versions.json 中，未重新分发 patch 源码。

仓库提供的是本机演示工具：下载后执行启动脚本，在本机浏览器配置客户资源。GitHub Pages不能执行此项目的Python后端，不应把本机控制接口或含客户配置的服务直接暴露到公网。

`VALIDATION.md` 记录本次实际完成的验证及限制。发布前应在你的目标账号、区域和 OpenClaw 镜像上再做一次演示彩排。
