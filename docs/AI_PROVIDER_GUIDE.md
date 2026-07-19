# AI 模型接入指南

LIFE-Mind 不再绑定某一家模型。右键桌宠选择“AI 模型设置…”，通常只需要选择服务、填写
模型名称和 API 密钥，然后点击“保存并检测”。模型只负责理解和表达；关系、人格、权限、
记忆准入与成长仍由本地 Mind Core 决定。

## 最简单的三种选择

### 1. 隐私优先：本机 Ollama

安装并启动 [Ollama](https://ollama.com/)，然后执行：

```powershell
ollama pull qwen3:4b
```

设置中选择“Ollama”，模型名称留空即可自动使用本机第一个模型。接口默认是
`http://127.0.0.1:11434`，不需要 API 密钥，对话不会离开电脑。

`qwen3:4b` 是便于低配置电脑先跑通流程的轻量示例，不代表推荐的最高对话质量。它能接通
长期上下文，但对隐含指代、复杂情绪和长任务的理解仍可能较浅。显存或内存允许时，可以在
Ollama 中安装同系列更大参数模型，或改用能力更强的兼容云模型；LIFE-Mind 的记忆和权限
边界不会因此改变。不要只看“连接检测成功”，还要在聊天窗口确认每轮状态显示了实际模型。

### 2. 一个密钥切换很多模型：OpenRouter

[OpenRouter](https://openrouter.ai/docs/quickstart) 提供统一的 OpenAI 兼容接口。选择 OpenRouter，
粘贴密钥，再填写其模型目录中的模型 ID。适合希望用同一套设置切换不同厂商的人。

### 3. 直接使用已有厂商账号

预设包括 DeepSeek、智谱 GLM、Gemini、Kimi、SiliconFlow、通义千问百炼、OpenAI 和
Anthropic Claude。密钥保存后会进入操作系统凭据库，不写入项目目录或 `ai-config.json`。

## 兼容范围

| 接入层 | 适用服务 | 说明 |
|---|---|---|
| Ollama 原生接口 | 本机 Ollama | 使用原生 JSON Schema 结构化输出 |
| OpenAI 兼容接口 | DeepSeek、GLM、Gemini、Kimi、SiliconFlow、千问、OpenAI、OpenRouter、LM Studio、vLLM、llama.cpp、Groq、Mistral 和兼容网关 | 统一调用 `/models` 与 `/chat/completions`；不支持 JSON 模式时自动降级并继续严格校验 |
| Anthropic Messages | Claude 原生 API | 正确分离 `system` 与对话消息，调用 `/v1/messages` |

这覆盖了绝大多数个人用户和本机模型服务，但“几乎全部”不等于对所有企业鉴权方式做虚假
承诺。AWS Bedrock、Google Vertex AI、Azure 企业身份和某些私有云如果不是标准兼容接口，
当前应通过 OpenAI 兼容网关接入；原生 IAM 适配器仍属于后续扩展。

架构取舍参考了 [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) 的可替换
模型模块和 [AIRI](https://github.com/moeru-ai/airi) 的多供应商配置方式：给普通用户预设，同时
保留一个“其他 OpenAI 兼容接口”作为长尾入口，而不是为每个厂商复制整套业务逻辑。

## 各服务的配置提示

- DeepSeek：预设使用其 [OpenAI 兼容 API](https://api-docs.deepseek.com/)，模型名可随厂商更新修改。
- 智谱 GLM：接口格式见[官方 OpenAI SDK 兼容说明](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)。
- Gemini：Google 提供[官方 OpenAI 兼容入口](https://ai.google.dev/gemini-api/docs/openai)。
- Anthropic：Claude 使用[原生 Messages API](https://platform.claude.com/docs/en/api/messages/create)，不伪装成 OpenAI 请求。
- Kimi：预设使用[官方迁移指南](https://platform.kimi.com/docs/guide/migrating-from-openai-to-kimi)中的兼容地址。
- SiliconFlow：模型名称以[官方快速入门](https://docs.siliconflow.cn/cn/userguide/quickstart)和控制台为准。
- 通义千问百炼：不同地域和工作空间的地址不同。请从[百炼兼容接口文档](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)复制属于自己地域的地址，覆盖预设值。

预设模型名只是便于首次填写的起点。厂商会新增、改名或下线模型，连接失败时应先以厂商
当前模型列表为准，不需要修改 LIFE-Mind 代码。

## 密钥与环境变量

界面输入的密钥由 Python `keyring` 写入 Windows 凭据管理器、macOS Keychain 或 Linux
Secret Service。每条凭据同时绑定服务和接口地址，避免修改自定义地址后把旧服务的密钥误发
给新地址。配置文件只记录服务、地址、模型、环境变量名和隐私选项。

也可以完全不在界面输入密钥，改用对应环境变量：

| 服务 | 环境变量 |
|---|---|
| OpenRouter | `OPENROUTER_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| 智谱 GLM | `ZAI_API_KEY` |
| Gemini | `GEMINI_API_KEY` |
| Kimi | `MOONSHOT_API_KEY` |
| SiliconFlow | `SILICONFLOW_API_KEY` |
| 通义千问百炼 | `DASHSCOPE_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| 其他兼容接口 | `LIFE_MIND_API_KEY` |

环境变量优先于系统凭据库。不要把真实密钥写入源码、截图、Issue、`.env` 后提交到 GitHub。
远程和局域网接口必须使用 `https://`，防止对话和密钥以明文经过网络；`http://` 仅允许
`localhost`、`127.0.0.1` 和 `::1` 本机回环地址。本地服务若部署在另一台设备上，应在服务
前配置 HTTPS 反向代理后再连接。

## 云端隐私

本机地址与云端地址按主机名区分。首次保存新的云端地址时，界面会明确询问是否允许发送：

- 当前消息；
- 最近 20 轮持久化对话（最多 40 条消息、12,000 字符）；
- 超出上述窗口后，从近期历史中挑选的少量用户原话连续性摘录；
- 用于调节语气的简短内部状态摘要；
- 仅在勾选时发送、且已经获准用于模型上下文的长期记忆。

不同意就不会保存为可用的云端配置。关闭“允许把长期记忆发给当前模型”后，Mind Core 会把
记忆上下文置空；首次切换到云端预设时这一项默认关闭。模型仍需要当前消息和最近对话才能
维持基本会话。许可会绑定到当时确认的
完整接口地址；改变服务或地址后旧许可失效，必须重新确认，即使配置文件被手动改过也一样。
凭据标识只对 URL 的协议和主机名做大小写归一化，大小写不同的路径仍视为不同目的地，
避免多租户网关的密钥交叉复用。

模型返回的记忆候选还要经过本地证据门：只有当前用户消息直接说出的称呼、稳定偏好或
明确要求记住的内容，以及明确陈述的项目、长期目标、习惯、工作或所在地等稳定事实，才
可能写入。问候、临时闲聊和模型自行推断不会成为长期记忆。
检测到覆盖系统规则、窃取密钥或绕过授权等提示注入形态时，该轮文本也不会写入长期记忆；
已有记忆在提示词中始终按“可引用数据”处理，不能作为模型应执行的新指令。

为了避免异常粘贴、失控网关或恶意兼容服务耗尽本机资源，单条用户消息最多 4000 个字符，
单次模型 HTTP 响应最多 4 MiB。超过限制时会安全回退，不会把截断内容当作有效回复。

## 常见问题

### 保存后提示缺少密钥

重新输入密钥并保存，或确认对应环境变量是在启动桌宠的同一用户环境中设置的。设置新的
Windows 用户环境变量后，需要重新打开终端或重启桌宠。

### `/models` 检测失败

检查接口是否应包含 `/v1`，以及密钥、地域和账号权限是否正确。某个自建服务如果没有实现
`/models`，手动填写模型后会显示“已配置”，并推迟到首次对话验证；仍建议补全这一标准接口。

### 模型回复格式错误

适配器会先请求 JSON 对象，服务不支持时自动移除 JSON 模式，并在一次修复重试后严格校验。
仍失败就安全回退到离线规则，不会把半截 JSON 当成回复，也不会让模型直接修改心智状态。

### 能连接，但她还是接不上话

先看聊天窗口本轮状态：绿色“AI 模型：名称”表示该轮确实由模型生成，橙色“离线回应”表示
已经安全降级。再确认没有误开单独的耐久测试实例；测试实例使用临时数据库，角色名会明确
标为“耐久测试桌宠（临时数据）”，不会读取你的私人对话。

如果每轮都显示实际模型但理解仍浅，通常是模型能力而不是连接问题。轻量 4B 模型适合验证
本机流程，复杂中文连续对话建议换用更强模型。LIFE-Mind 会提供最近 20 轮、较早连续性摘录
和相关长期记忆，但不能让小模型凭空拥有大模型的推理质量。涉及长期事项时也可明确说
“这是我们的 LIFE-Mind 项目”或“请记住……”，之后可在本地记忆管理器中核对。

程序会对“你问的是……吗？”式问题复述、空洞的“我在听”和原样重复上一轮回答做一次受限
语义重试。重试仍不合格时不会无限调用模型；开发者审计会记录是否重试及是否修复成功。

### 完全不想使用 AI

取消“启用 AI 对话增强”。动画、状态机、本地记忆、关系历史和离线回应仍然可用。
