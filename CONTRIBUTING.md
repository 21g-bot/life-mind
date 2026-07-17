# Contributing

感谢参与 LIFE-Mind。提交改动前请遵守以下边界：

1. 不提交真实聊天、记忆数据库、用户画像或盲测答卷；
2. 不提交没有明确再发布权的角色图片、第三方来源包、音乐或模型文件；
3. 新动作库必须使用独立 `identity`，所有 PNG 帧尺寸一致并带透明通道；
4. 新的公开 UI 字段必须先通过黑箱边界审查；
5. 提交前运行：

```powershell
python -m pip install -r requirements-dev.txt
python -B tools/validate_contract.py life-package examples/life-package.demo.json
python -B tools/validate_contract.py capability-manifest examples/capability-manifest.demo.json
python -B tools/validate_contract.py experience examples/experience.demo.json
python -B -m unittest discover -s tests
python -B tools/check_public_release.py
python -B tools/check_markdown_links.py
```

Bug 报告请提供最小复现步骤、Python 版本和脱敏后的错误信息。不要上传 `%LOCALAPPDATA%\LIFE-Mind` 原始目录。

准备认领路线图工作时，请先阅读[实施任务](docs/IMPLEMENTATION_BACKLOG.md)，并使用 GitHub 的
“实施任务”模板填写稳定任务编号、非目标、验收条件、安全影响和第三方许可证。参考项目的
思想可以研究，但复制代码或素材前必须单独确认许可证兼容性并记录来源。

提交到本仓库的贡献默认按照仓库的 Apache License 2.0 提供。若某项内容不能按该许可证
发布，请不要通过 Pull Request 提交，并在讨论中明确说明权利边界。
