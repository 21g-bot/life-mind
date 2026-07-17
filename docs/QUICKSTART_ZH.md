# LIFE-Mind 新手教程（Windows）

这份教程只要求会复制命令。第一次运行会生成一个简单的绿色种子演示角色，不包含项目作者的私人桌宠图片、聊天记录或成长数据库。

## 1. 准备软件

安装：

- Windows 10 或 Windows 11；
- Python 3.12；
- 可选：Ollama，用于本地 AI 对话。

打开 PowerShell，确认 Python 可用：

```powershell
py -3.12 --version
```

## 2. 下载并安装

```powershell
git clone https://github.com/21g-bot/life-mind.git
cd life-mind
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

如果 PowerShell 不允许激活虚拟环境，可以不激活，后面的 `python` 改成 `.\.venv\Scripts\python.exe`。

## 3. 第一次启动

```powershell
python -B run_pet.py
```

首次运行如果没有私人素材，程序会在 `.cache/demo-character/` 自动生成演示角色。这个目录不会进入 Git。

常用操作：

- 左键拖动：移动桌宠；
- 双击：打招呼；
- 右键：聊天、选择活动、打开个人房间、配置本地 AI；
- `Esc`：退出。

只检查动作库、不打开窗口：

```powershell
python -B run_pet.py --check
```

## 4. 接入本地 AI（可选）

安装并启动 Ollama 后执行：

```powershell
ollama pull qwen3:4b
```

启动桌宠，右键选择“本地 AI 设置…”，检测连接即可。没有 Ollama 时桌宠仍能使用离线规则运行，只是自然语言能力会变弱。

## 5. 换成自己的角色

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

也可以设置本机环境变量，让普通启动一直使用它：

```powershell
setx LIFE_MIND_ASSET "C:\path\to\my-pet"
setx LIFE_MIND_CHARACTER_IDENTITY "my-pet-v1"
setx LIFE_MIND_NAME "我的桌宠"
```

第二项是可选的身份锁：设置后，程序会拒绝加载其他 `identity` 的动作库。第三项覆盖窗口、房间、托盘和 AI 提示中显示的角色名称。重新打开终端后环境变量才生效。

## 6. 私人数据在哪里

默认保存在：

```text
%LOCALAPPDATA%\LIFE-Mind\
├── life-mind.db
├── desktop-pet.json
└── ai-config.json
```

这里包含聊天记忆、成长事件、窗口位置和 AI 设置，不在仓库目录内。备份项目源码时不要顺手复制这个目录；公开问题截图前也应检查是否包含真实对话。

项目中的以下目录同样默认不上传：

```text
assets/character/
source/
tmp/
data/
.cache/
.deps/
```

## 7. 运行测试

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

## 8. 常见问题

### 提示找不到 Pillow

```powershell
python -m pip install -r requirements.txt
```

### 桌宠没有自然语言回复

这是 Ollama 未启动或未安装模型，不影响离线状态机。运行 `ollama list` 检查模型。

### 自定义角色无法加载

先运行：

```powershell
python -B run_pet.py --asset C:\path\to\my-pet --check
```

重点检查 `manifest.json`、帧命名、透明通道、统一尺寸和可选的身份锁。

当前参考宿主直接读取上述动画库；完整 Life Package 的安装与切换流程仍在开发中。协议格式
和当前能力边界见[三项公开协议](PUBLIC_CONTRACTS.md)。
