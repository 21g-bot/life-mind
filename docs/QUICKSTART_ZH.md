# LIFE-Mind 新手教程（Windows）

这份教程只要求会复制命令。第一次运行会生成一个简单的绿色种子演示角色，不包含项目作者的私人桌宠图片、聊天记录或成长数据库。

## 1. 准备软件

只想直接使用桌宠时，需要：

- Windows 10 或 Windows 11；
- 从本项目 GitHub Releases 下载的 Windows x64 便携包。

想从源码运行或参与开发时，再安装：

- Python 3.12；
- 可选：Ollama，用于完全本机的 AI 对话；也可使用已有云端模型账号。

打开 PowerShell，确认 Python 可用：

```powershell
py -3.12 --version
```

## 2. 最简单：运行 Windows 便携版

1. 打开 [GitHub Releases](https://github.com/21g-bot/life-mind/releases)；
2. 下载 `LIFE-Mind-v0.1.2-windows-x64.zip` 和同名 `.sha256` 文件；
3. 完整解压 ZIP，不要直接在压缩包预览窗口中运行；
4. 双击解压目录里的 `LIFE-Mind.exe`。

当前预览版没有商业代码签名证书，Windows SmartScreen 可能显示“未知发布者”。请确认下载
地址属于 `github.com/21g-bot/life-mind`。需要核对文件时，在 ZIP 所在目录运行：

```powershell
Get-FileHash .\LIFE-Mind-v0.1.2-windows-x64.zip -Algorithm SHA256
Get-Content .\LIFE-Mind-v0.1.2-windows-x64.sha256
```

两处 64 位校验值应完全一致。便携版不修改系统安装目录；运行数据仍保存在第 7 节所列的
用户本地目录。

## 3. 开发者：从源码运行

```powershell
git clone https://github.com/21g-bot/life-mind.git
cd life-mind
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

如果 PowerShell 不允许激活虚拟环境，可以不激活，后面的 `python` 改成 `.\.venv\Scripts\python.exe`。

## 4. 第一次启动

```powershell
python -B run_pet.py
```

源码版首次运行如果没有私人素材，会在 `.cache/demo-character/` 自动生成演示角色；便携版
会生成到 `%LOCALAPPDATA%\LIFE-Mind\demo-character\`。两者都不会被加入 GitHub 发行包。

常用操作：

- 左键拖动：移动桌宠；
- 双击：打招呼；
- 右键：聊天、选择活动、打开个人房间、配置 AI 模型；
- `Esc`：退出。

只检查动作库、不打开窗口：

```powershell
python -B run_pet.py --check
```

## 5. 接入 AI（可选）

最重视隐私时，安装并启动 Ollama：

安装并启动 Ollama 后执行：

```powershell
ollama pull qwen3:4b
```

启动桌宠，右键选择“AI 模型设置…”，模型名称留空，保存并检测即可。

如果想使用 DeepSeek、GLM、Gemini、Kimi、千问、OpenRouter、OpenAI、Claude 或其他兼容
服务，在同一窗口选择厂商、填写模型和 API 密钥。密钥进入 Windows 凭据管理器，不会写入
项目文件。云端连接会先说明发送哪些数据并询问许可；长期记忆共享可以关闭。

没有任何模型时桌宠仍能使用离线规则运行，只是自然语言能力会变弱。各服务的地址、环境
变量和故障排查见 [AI 模型接入指南](AI_PROVIDER_GUIDE.md)。

右键“聊天”会打开连续对话窗口，不会在每次回复后自动关闭。窗口显示最近 20 条消息，关闭
窗口或重启桌宠后仍可接着聊；标题右侧和每轮回复后的状态会显示实际模型。如果状态显示
“离线回应”，说明模型未启用、未连接或本轮返回无效，不能把这类回复误认为 AI 已接入。

需要她跨较长时间记住的稳定事实，可以直接说“我正在开发……项目”“我的长期目标是……”
或“请记住……”。这些信息仍要经过本地记忆准入，并能在“管理本地记忆”里纠正或删除。
日常闲聊会保留为本机对话历史，但不会全部冒充成永久人格事实。

## 6. 换成自己的角色

动作库是一个带透明 PNG 帧和 `manifest.json` 的目录。最小结构：

```text
my-pet/
├── manifest.json
├── idle/
│   ├── frame_000.png
│   └── frame_001.png
└── blink/
    ├── frame_000.png
    └── frame_001.png
```

最小清单示例：

```json
{
  "format": 2,
  "style": "refined-pixel-art",
  "identity": "my-pet-v1",
  "display_name": "我的桌宠",
  "default_clip": "idle",
  "clips": {
    "idle": {"duration_ms": 90, "loop": true, "frames": 2},
    "blink": {"duration_ms": 60, "loop": false, "frames": 2}
  }
}
```

要求：

- 文件名使用 `frame_000.png`、`frame_001.png` 的格式；
- 所有帧尺寸相同，并带 RGBA 透明通道；
- `identity` 不能为空；
- `display_name` 用于窗口、房间、托盘和 AI 提示中的角色名称；
- `idle` 必须存在；
- 其他动作可以逐步增加，推荐名称见演示角色清单。

运行自定义角色：

```powershell
python -B run_pet.py --asset C:\path\to\my-pet
```

便携版可以直接在 `LIFE-Mind.exe` 同级创建 `character\`，并把 `manifest.json` 和各动作目录
放进去；也可以使用下面的 `LIFE_MIND_ASSET` 环境变量指向任意位置。

也可以设置本机环境变量，让普通启动一直使用它：

```powershell
setx LIFE_MIND_ASSET "C:\path\to\my-pet"
setx LIFE_MIND_CHARACTER_IDENTITY "my-pet-v1"
setx LIFE_MIND_NAME "我的桌宠"
```

第二项是可选的身份锁：设置后，程序会拒绝加载其他 `identity` 的动作库。第三项覆盖窗口、房间、托盘和 AI 提示中显示的角色名称。重新打开终端后环境变量才生效。

## 7. 私人数据在哪里

默认保存在：

```text
%LOCALAPPDATA%\LIFE-Mind\
├── life-mind.db
├── desktop-pet.json
├── ai-config.json
├── backups\       # 最多保留 7 个经过完整性检查的数据库快照
└── recovery\      # 损坏或恢复前的数据库副本，不会自动上传
```

这里包含聊天记忆、成长事件、窗口位置和 AI 设置，不在仓库目录内。备份项目源码时不要顺手复制这个目录；公开问题截图前也应检查是否包含真实对话。

正常退出会自动备份；也可以右键桌宠选择“备份本地数据”。需要排查或手动恢复时，在项目目录运行：

```powershell
python -B run_pet.py --doctor
python -B run_pet.py --backup-now
python -B run_pet.py --restore-latest-backup
```

Windows 便携版把 `python -B run_pet.py` 换成 `.\LIFE-Mind.exe`；维护结果会显示在系统对话框中。

第一条只输出脱敏健康状态，适合复制到 GitHub Issue；第二条立即创建一致性快照；第三条会先把
当前数据库移到 `recovery\`，再恢复最近一个通过完整性检查的备份。不要在桌宠仍运行时执行手动
恢复。完整恢复规则见[数据可靠性与恢复](DATA_RELIABILITY.md)。

项目中的以下目录同样默认不上传：

```text
assets/character/
source/
tmp/
data/
.cache/
.deps/
```

## 8. 运行测试

```powershell
python -m pip install -r requirements-dev.txt
python -B tools/validate_contract.py life-package examples/life-package.demo.json
python -B tools/validate_contract.py capability-manifest examples/capability-manifest.demo.json
python -B tools/validate_contract.py experience examples/experience.demo.json
python -B -m unittest discover -s tests
python -B -m life_mind.simulator --repeat 30
python -B tools/check_public_release.py
python -B tools/check_markdown_links.py
```

协议、核心测试和模拟通过，说明公开数据边界、状态机、记忆治理和动作加载器基本正常。后两项检查准备公开的
文件中是否混入数据库、私人素材、私人角色身份、缓存、密钥形态、本机绝对路径或失效文档链接。

## 9. 常见问题

### 提示找不到 Pillow

```powershell
python -m pip install -r requirements.txt
```

### 桌宠没有自然语言回复

本机模式先运行 `ollama list` 检查 Ollama 和模型；云端模式在“AI 模型设置…”中检查接口、
模型名和密钥。连接失败不影响离线状态机。

### 自定义角色无法加载

先运行：

```powershell
python -B run_pet.py --asset C:\path\to\my-pet --check
```

重点检查 `manifest.json`、帧命名、透明通道、统一尺寸和可选的身份锁。

当前参考宿主直接读取上述动画库；完整 Life Package 的安装与切换流程仍在开发中。协议格式
和当前能力边界见[三项公开协议](PUBLIC_CONTRACTS.md)。
