# GitHub 开源发布清单

## 开源边界

建议公开的是引擎、桌面外壳、演示角色生成器、测试、通用工具和教程。下面内容留在本机：

| 内容 | 位置 | 是否公开 |
|---|---|---|
| Python 框架与测试 | `life_mind/`、`tests/` | 是 |
| 公开协议、Schema 与中立示例 | `schemas/`、`examples/` | 是 |
| 中立演示角色 | 由代码生成到 `.cache/demo-character/` | 只公开生成器，不提交生成结果 |
| 私人角色原图和动作帧 | `assets/character/`、`source/` | 否 |
| 对话、记忆、关系、成长数据库及恢复副本 | `%LOCALAPPDATA%\LIFE-Mind\life-mind.db*`、`backups\`、`recovery\` | 否 |
| 窗口位置和 AI 设置 | `%LOCALAPPDATA%\LIFE-Mind\*.json` | 否 |
| QA 截图、第三方来源包、盲测答卷 | `tmp/`、`data/` | 否 |
| 私人动作库生成/稳定化脚本 | `tools/build_pixel_animation_pack.py`、`tools/stabilize_animation_pack.py` | 否 |
| 本地依赖与缓存 | `.deps/`、`.cache/`、`.venv/` | 否 |

Windows 便携包由 GitHub Actions 在干净的 Windows/Python 3.12 环境构建，只收录冻结后的
程序、`LICENSE`、`NOTICE` 和 `README.md`。公开演示动作会在首次运行时生成，私人角色和
用户数据不会被打入 ZIP。

当前本机的缓存、素材和依赖合计超过 1 GB，不能直接执行不检查的 `git add -f .`。

## 发布前步骤

项目目前可以先在本地初始化，不需要立刻连接 GitHub：

```powershell
git init
git branch -M main
python -B tools/check_public_release.py
python -B tools/check_markdown_links.py
python -B tools/validate_contract.py life-package examples/life-package.demo.json
python -B tools/validate_contract.py capability-manifest examples/capability-manifest.demo.json
python -B tools/validate_contract.py experience examples/experience.demo.json
git add .
git status --short
git diff --cached --stat
```

确认状态列表中没有以下内容：

- `assets/character/` 下的 PNG、GIF、PSD 或动作帧；
- `tmp/`、`source/`、`.deps/`、`.cache/`；
- `.db`、`.db-wal`、`.db-shm`；
- 记忆导出、盲测答卷、真实聊天截图；
- API Key、Token、Cookie、邮箱或本机用户目录。

如果某个私人文件曾经被 Git 跟踪，新增 `.gitignore` 并不会自动取消跟踪。发布前应先从 Git 索引移除，再检查暂存区；不要删除唯一的本地原件。

## 许可证与维护者

公开框架采用 Apache License 2.0，版权署名为 `不语（Bùyǔ，GitHub: 21g-bot）`。仓库根目录中的
`LICENSE` 是完整许可证正文，`NOTICE` 记录项目署名与私人内容排除说明。

还要确认：

1. 仓库中的文字、代码和演示角色生成器可以公开；
2. 私人角色美术、第三方来源文件和音乐没有被强制加入；
3. 公开参考人物弧只使用 `simulations/demo_growth.json`，本机人物设定和视觉记录保持忽略；
4. README 中的仓库地址、许可证名称和维护者署名与 GitHub 仓库一致。

## 创建 GitHub 仓库后

在 GitHub 创建一个空仓库，不要额外生成 README，然后运行：

```powershell
git remote add origin https://github.com/21g-bot/life-mind.git
git commit -m "Initial open-source framework"
git push -u origin main
```

推送前再运行一次：

```powershell
python -B tools/check_public_release.py
python -B tools/check_markdown_links.py
git status
```

## Windows 发行版与标签

`windows-package.yml` 会在 PR 和 `main` 上构建便携 ZIP，执行冻结版 `--release-check`，检查压缩包
路径、Windows PE 文件和 SHA256。只有推送与代码版本一致的 `v*` 标签，才会创建 GitHub
Release。

发布前必须先确认 PR 上的 `tests` 与 `windows-package` 都通过，然后创建带说明的标签：

```powershell
$version = "0.1.2" # 每次发布前改成准备发布的版本
git switch main
git pull --ff-only
git tag -a "v$version" -m "LIFE-Mind v$version"
git push origin "v$version"
```

标签工作流会读取对应的 `docs/releases/v<版本>.md`，上传 ZIP 和 `.sha256`。发布后再下载一次资产，
核对校验值和实际启动结果。不要手工上传本机 `dist/`、私人动作库或 `%LOCALAPPDATA%` 数据。

当前 EXE 未使用商业代码签名证书，因此文档必须保留 SmartScreen“未知发布者”和 SHA256
核验说明。预览版也不能替代 8 小时稳定性与真实体验者盲测这两项正式 MVP 人工闸门。
