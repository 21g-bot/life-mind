# LIFE-Mind

> Living Identity, Feedback and Experience Mind Engine
> 开放式角色生命引擎，以及它的本地像素桌宠参考实现。

LIFE-Mind 让角色通过工作、社交、独处、失败和自主选择，逐渐形成可追溯的关系历史与人物
成长弧。她的变化遵循“事件 → 理解 → 情绪 → 选择 → 结果 → 反思 → 证据化成长”，而不是
只靠角色 Prompt、聊天记录或好感度加减。

> 她不是被设定成谁，而是会因为与你和这个世界共同生活，逐渐成为谁。

技术上，Mind Core 与桌面表现、模型和外部能力分离，可以被不同桌宠宿主嵌入。当前仓库
交付的是确定性心智内核、Windows/Tkinter 像素 Sprite 参考宿主、黑箱个人房间和调试工具；
插件沙箱、Creator Studio、Live2D/Spine 和跨平台发行仍在[路线图](docs/ROADMAP.md)中。

框架设计不是凭空堆功能：我们研究了 Open-LLM-VTuber、AIRI、VPet、Petdex、OpenPets、
DyberPet、desktopPet/eSheep 和 Claude Desktop Buddy 的官方资料，吸收其适配器、玩法、分发、安全、
桌面空间和状态表达优点，再用 LIFE-Mind 的经验—关系—成长闭环重新组合。详见
[参考项目研究与吸收矩阵](docs/REFERENCE_PROJECT_STUDY.md)。

## 当前交付边界

| 部分 | 当前可用 | 尚未完成 |
|---|---|---|
| Mind Core | 状态、社会评价、关系、记忆、仲裁、单人物弧 | 多人物弧与自动人格漂移检测 |
| Pet Host | Windows 像素动画、气泡、托盘、房间、调试器 | 多渲染器、桌面空间感知、完整玩法系统 |
| Capability Runtime | Manifest 与显式授权判定原语 | 第三方插件加载器、进程沙箱、配额执行、MCP |
| Creator 工具 | JSON Schema、示例、CLI 校验 | 图形编辑器、包安装与内容市场 |

完整分层和边界见[平台架构](docs/PLATFORM_ARCHITECTURE.md)。

## 开源边界

本仓库公开：

- 心智引擎、桌面窗口、动作状态机和多供应商 AI 适配层；
- 数据模型、SQLite 持久化、记忆治理和成长证据；
- 程序生成的中立演示角色、测试、通用工具和中文教程。

本仓库不包含任何维护者或使用者的私人角色美术、动画包、对话、记忆、日记、关系数据、
本地模型设置或用户档案。新克隆的仓库会在首次启动时生成“小芽（演示）”，不会回退到
第三方壁纸、GIF、旧模型或私人素材。

## 快速开始

当前主要支持 Windows。普通用户可从
[GitHub Releases](https://github.com/21g-bot/life-mind/releases) 下载
`LIFE-Mind-v0.1.2-windows-x64.zip`，完整解压后双击 `LIFE-Mind.exe`。便携版无需安装
Python；首次启动会在用户本地目录生成中立演示角色。

> 当前 EXE 没有商业代码签名证书，Windows SmartScreen 可能显示“未知发布者”。请只从本
> 仓库 Release 下载，并用随包提供的 `.sha256` 文件核对完整性。

开发者或希望自行审阅源码的用户，建议使用 Python 3.12：

```powershell
git clone https://github.com/21g-bot/life-mind.git
cd life-mind
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -B run_pet.py --check
python -B run_pet.py
```

首次素材检查应显示：

```text
identity: life-mind-demo-seed
display_name: 小芽（演示）
clips: 16
frames: 192
```

完整步骤见 [Windows 新手教程](docs/QUICKSTART_ZH.md)。

## 基本操作

- 左键拖动：移动桌宠；
- 双击：打招呼；
- 右键：对话、选择活动、打开个人房间、切换勿扰、管理本地记忆和配置 AI 模型；
- Esc：退出。

桌宠不会自行在桌面巡游。独处动作由状态机根据精力、心情、最近互动、活动持续时间和
冷却时间选择，不会连续随机触发。

## AI 模型（本机或云端）

自然语言能力可以连接本机 [Ollama](https://ollama.com/)。例如：

```powershell
ollama pull qwen3:4b
```

也可以从右键“AI 模型设置…”选择 OpenRouter、DeepSeek、智谱 GLM、Gemini、Kimi、
SiliconFlow、通义千问、OpenAI、Anthropic、LM Studio 或其他 OpenAI 兼容接口。API 密钥
保存在操作系统凭据库，不进入项目文件；新的云端地址必须先获得明确的数据发送许可，长期
记忆共享可单独关闭。

没有运行模型时会使用确定性离线规则，记忆与状态机仍然可用。模型只负责理解和自然表达，
不能直接修改关系、成长阶段、权限或内部状态。完整配置见
[AI 模型接入指南](docs/AI_PROVIDER_GUIDE.md)。

“聊天”现在是一个可连续输入的本地会话窗口，会显示最近 20 条消息。Mind Core 每次生成会
读取持久化数据库中的最近 20 轮对话（最多 40 条消息、12,000 字符），并从更早对话中选择
少量用户亲自说过的连续性摘录；关闭窗口或重启程序后仍能继续。姓名、稳定偏好、项目、
长期目标、习惯等经过准入的事实会单独进入可查看和删除的长期记忆，而不是只依赖模型的
临时上下文。界面会显示本轮实际使用的模型；出现“离线回应”就表示本轮没有成功调用 AI。
聊天窗口提供“清空记录”：它会清除聊天历史、后续 AI 上下文和心智事件中的对话原文；已经
单独准入的长期记忆仍由“管理本地记忆”独立纠正或删除，避免一个含糊按钮误删两类数据。
清除或删除后，普通自动备份会轮换成一份新的脱敏快照；数据库损坏时隔离的 `recovery\`
副本不会被程序擅自删除，需要用户确认当前数据健康后自行管理。

## 黑箱体验

普通用户只看到：

- 当前心情；
- 单一总体好感度；
- 少量达到公开门槛的重要日记；
- 动作、语气、节奏、主动活动和长期选择。

内部需要、关系分项、成长门槛、候选动作得分、完整回忆、模型提示词和审计轨迹只在显式
开发者模式中用于调试：

```powershell
python -B run_pet.py --developer-mode
```

设计说明见 [黑箱体验与公开信息边界](docs/BLACK_BOX_EXPERIENCE.md)。

## 自定义角色

公开版支持通过动作库替换演示角色：

```powershell
$env:LIFE_MIND_ASSET="D:\path\to\my-character"
$env:LIFE_MIND_CHARACTER_IDENTITY="my-character-v1"
$env:LIFE_MIND_NAME="我的桌宠"
python -B run_pet.py --check
python -B run_pet.py
```

便携版也可以把动作库放到 `LIFE-Mind.exe` 同级的 `character\` 目录；程序生成的演示素材
和所有运行数据始终写入 `%LOCALAPPDATA%\LIFE-Mind\`，不会写进程序内部目录。

动作库必须声明 `style=refined-pixel-art`、非空 `identity`、固定画布和透明 PNG 帧。详细格式：

- [角色配置模板](docs/CHARACTER_TEMPLATE.md)
- [像素角色与动画素材指南](docs/VISUAL_ASSET_GUIDE.md)
- [私人角色目录说明](assets/character/README.md)

## 本地数据

运行数据默认保存在仓库之外：

```text
%LOCALAPPDATA%\LIFE-Mind\desktop-pet.json
%LOCALAPPDATA%\LIFE-Mind\life-mind.db
%LOCALAPPDATA%\LIFE-Mind\ai-config.json
%LOCALAPPDATA%\LIFE-Mind\backups\
%LOCALAPPDATA%\LIFE-Mind\recovery\
```

正常退出时会生成经过 SQLite 完整性检查的原子快照，并只保留最近 7 份。启动发现数据库损坏时，
程序先把原文件及 WAL 边车移入 `recovery\`，再尝试恢复最近有效备份；不会直接覆盖或删除损坏副本。
右键桌宠可选择“备份本地数据”。维护者还可以运行：

```powershell
python -B run_pet.py --doctor
python -B run_pet.py --backup-now
python -B run_pet.py --restore-latest-backup
```

`--doctor` 输出可附在 Issue 中的脱敏报告，不包含本机绝对路径、对话、记忆正文、API 密钥或模型
接口。恢复命令会先隔离当前数据库，因此恢复后仍保留反悔和人工检查的可能。详细设计见
[数据可靠性与恢复](docs/DATA_RELIABILITY.md)。

维护者可以用一条命令验证 10,000 条长期事件的重放、备份、损坏恢复、数据库体积和内存预算：

```powershell
python -B tools\benchmark_data_reliability.py --events 10000
```

该命令只使用 `tmp/` 下的临时数据库，不读取或修改个人桌宠数据。

仓库还会忽略 `.cache/`、`.deps/`、`source/`、`tmp/`、`data/`、数据库、环境变量文件和
私人角色目录。发布前检查器会再次扫描 Git 候选文件。

## 技术结构

```text
用户输入 / 自主活动 / 获得授权的外部事件
        ↓
Experience Protocol → 社会评价 → 候选行为 → L0 安全仲裁
        ↓                         ↓
SQLite 事件与记忆             Pet Host 表现意图
        ↓
确定性回放 → 成长证据 → 黑箱公开投影 / 开发者调试
```

主要模块：

- `life_mind/domain/`：事件、身体、需要、关系、成长和记忆契约；
- `life_mind/contracts.py`：Life Package、Capability Manifest 和 Experience Protocol；
- `life_mind/ports.py`：模型、语音、能力与不同 Pet Host 的扩展端口；
- `life_mind/presentation.py`：把黑箱心智压缩成跨渲染器可读的表现意图；
- `life_mind/simulator.py`：无界面心智模拟与确定性回放；
- `life_mind/persistence.py`：结构化事件和完整仲裁轨迹持久化；
- `life_mind/database.py`：版本化迁移、完整性检查、原子备份、隔离恢复和脱敏诊断；
- `life_mind/mind.py`：统一状态、长期记忆与 AI 表达适配；
- `life_mind/behavior.py`：桌面动作状态机；
- `life_mind/apps/`：桌宠窗口、黑箱个人房间和系统托盘。

## 开发与验证

```powershell
python -m pip install -r requirements-dev.txt
python -B tools/validate_contract.py life-package examples/life-package.demo.json
python -B tools/validate_contract.py capability-manifest examples/capability-manifest.demo.json
python -B tools/validate_contract.py experience examples/experience.demo.json
python -B -m unittest discover -s tests
python -B -m life_mind.simulator --repeat 30
python -B tools/check_public_release.py
python -B tools/check_markdown_links.py
python -m pip install -r requirements-build.txt
python -B tools/build_windows_release.py
```

当前自动化套件覆盖心智、记忆、AI 适配、动画、公开边界和发行包规则。模拟器的公共参考人物弧位于
`simulations/demo_growth.json`。8 小时桌面稳定性和真实体验者行为盲测仍是正式 MVP 的人工
发布闸门，短时自动测试不能替代它们。

## 文档

- [项目蓝图](docs/PROJECT_BLUEPRINT.md)
- [平台架构与当前实现边界](docs/PLATFORM_ARCHITECTURE.md)
- [三项公开协议 0.1](docs/PUBLIC_CONTRACTS.md)
- [分阶段路线图](docs/ROADMAP.md)
- [参考项目研究与吸收矩阵](docs/REFERENCE_PROJECT_STUDY.md)
- [可直接建立 GitHub Issue 的实施任务](docs/IMPLEMENTATION_BACKLOG.md)
- [MVP 范围与验收标准](docs/MVP_ACCEPTANCE.md)
- [阶段 0：无界面心智模拟器](docs/STAGE_0_SIMULATOR.md)
- [行为、情绪与动画状态机](docs/BEHAVIOR_STATE_MACHINE.md)
- [桌宠心智集成与持久化](docs/STAGE_1_DESKTOP_INTEGRATION.md)
- [桌面外壳、托盘、勿扰与稳定性](docs/STAGE_1_DESKTOP_SHELL.md)
- [记忆治理与个人房间](docs/STAGE_2_MEMORY_AND_ROOM.md)
- [本地 AI 社会理解与安全边界](docs/STAGE_3_LLM_SOCIAL_SAFETY.md)
- [本机与云端 AI 模型接入指南](docs/AI_PROVIDER_GUIDE.md)
- [成长证据与行为盲测](docs/STAGE_4_GROWTH_VISIBILITY.md)
- [开源发布与隐私检查](docs/OPEN_SOURCE_RELEASE.md)
- [安全问题报告规范](SECURITY.md)
- [版本记录](CHANGELOG.md)

## 贡献与许可证

提交贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，并确保没有加入私人数据或无权再发布
的素材。

Copyright 2026 不语（Bùyǔ，GitHub: 21g-bot）。公开仓库内容使用
[Apache License 2.0](LICENSE)。私人角色素材和运行数据不属于开源发行内容，也不受该许可证
授权。
