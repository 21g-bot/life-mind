"""Provider-neutral AI adapters for LIFE-Mind.

The model is an interpreter and narrator.  It never receives authority to
change the deterministic mind state, permissions, relationships or growth.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse, urlsplit, urlunsplit


DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LIFE-Mind"
AI_CONFIG_PATH = DATA_DIR / "ai-config.json"


class LocalAIError(RuntimeError):
    pass


class ProviderHTTPError(LocalAIError):
    """HTTP error carrying a status code so compatibility fallbacks stay narrow."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = int(status)


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward provider credentials to a different origin."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        old = urlparse(request.full_url)
        new = urlparse(new_url)
        if (old.scheme, old.hostname, old.port) != (new.scheme, new.hostname, new.port):
            raise urllib.error.HTTPError(
                new_url,
                code,
                "模型接口尝试把请求重定向到其他来源，已拒绝",
                headers,
                file_pointer,
            )
        return super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    provider_id: str
    label: str
    protocol: str
    endpoint: str
    default_model: str
    api_key_env: str
    requires_key: bool
    remote: bool
    note: str = ""


PROVIDER_PRESETS = (
    ProviderPreset(
        "ollama", "Ollama（本机，推荐隐私优先）", "ollama",
        "http://127.0.0.1:11434", "", "", False, False,
        "自动读取本机已安装模型。",
    ),
    ProviderPreset(
        "lm-studio", "LM Studio / 本机 OpenAI 接口", "openai",
        "http://127.0.0.1:1234/v1", "", "", False, False,
        "也适用于 vLLM、llama.cpp 等本机兼容服务。",
    ),
    ProviderPreset(
        "openrouter", "OpenRouter（一个密钥，多家模型）", "openai",
        "https://openrouter.ai/api/v1", "", "OPENROUTER_API_KEY", True, True,
        "适合希望用一个入口切换多家模型的用户。",
    ),
    ProviderPreset(
        "deepseek", "DeepSeek", "openai",
        "https://api.deepseek.com", "deepseek-v4-flash", "DEEPSEEK_API_KEY", True, True,
    ),
    ProviderPreset(
        "zhipu", "智谱 GLM", "openai",
        "https://open.bigmodel.cn/api/paas/v4", "glm-5.1", "ZAI_API_KEY", True, True,
    ),
    ProviderPreset(
        "gemini", "Google Gemini", "openai",
        "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.5-flash",
        "GEMINI_API_KEY", True, True,
    ),
    ProviderPreset(
        "kimi", "Kimi / Moonshot", "openai",
        "https://api.moonshot.cn/v1", "kimi-k3", "MOONSHOT_API_KEY", True, True,
    ),
    ProviderPreset(
        "siliconflow", "硅基流动 SiliconFlow", "openai",
        "https://api.siliconflow.cn/v1", "", "SILICONFLOW_API_KEY", True, True,
    ),
    ProviderPreset(
        "qwen", "通义千问百炼（地址按地域修改）", "openai",
        "https://dashscope-us.aliyuncs.com/compatible-mode/v1", "qwen-plus",
        "DASHSCOPE_API_KEY", True, True,
        "中国内地等地域需粘贴百炼控制台给出的兼容接口地址。",
    ),
    ProviderPreset(
        "openai", "OpenAI", "openai",
        "https://api.openai.com/v1", "", "OPENAI_API_KEY", True, True,
    ),
    ProviderPreset(
        "anthropic", "Anthropic Claude（原生接口）", "anthropic",
        "https://api.anthropic.com", "claude-haiku-4-5-20251001",
        "ANTHROPIC_API_KEY", True, True,
    ),
    ProviderPreset(
        "custom-openai", "其他 OpenAI 兼容接口", "openai",
        "http://127.0.0.1:8000/v1", "", "LIFE_MIND_API_KEY", False, False,
        "适用于 Groq、Mistral、自建网关及其他兼容服务。",
    ),
)
PROVIDERS_BY_ID = {preset.provider_id: preset for preset in PROVIDER_PRESETS}


def provider_preset(provider_id: str) -> ProviderPreset:
    return PROVIDERS_BY_ID.get(provider_id, PROVIDERS_BY_ID["custom-openai"])


def credential_id(provider_id: str, endpoint: str) -> str:
    """Bind a vault entry to both provider and destination to prevent key reuse leaks."""

    normalized = _credential_endpoint_identity(endpoint)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"{provider_id}:{digest}"


def _credential_endpoint_identity(endpoint: str) -> str:
    """Normalize only URL components whose comparison is case-insensitive.

    URL paths can be case-sensitive.  Folding the whole endpoint would therefore
    let two distinct tenants or gateways share a credential-store entry.
    """

    raw = str(endpoint).strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return raw.rstrip("/")
    if not parsed.scheme or not parsed.hostname or parsed.username or parsed.password:
        return raw.rstrip("/")
    scheme = parsed.scheme.casefold()
    host = parsed.hostname.casefold()
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit(
        (scheme, netloc, parsed.path.rstrip("/"), parsed.query, parsed.fragment)
    )


def endpoint_is_remote(endpoint: str) -> bool:
    try:
        parsed = urlparse(endpoint)
        host = (parsed.hostname or "").casefold()
    except ValueError:
        return True
    if parsed.scheme not in {"http", "https"} or not host:
        return True
    return host not in {"localhost", "127.0.0.1", "::1"}


def endpoint_transport_allowed(endpoint: str) -> bool:
    """Allow HTTPS everywhere and plain HTTP only on the local loopback host."""

    try:
        parsed = urlparse(endpoint)
        host = parsed.hostname
    except ValueError:
        return False
    if not host or parsed.scheme not in {"http", "https"}:
        return False
    return parsed.scheme == "https" or not endpoint_is_remote(endpoint)


def _safe_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def _safe_timeout(value: object) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError, OverflowError):
        return 45.0
    if not math.isfinite(resolved):
        return 45.0
    return max(2.0, min(180.0, resolved))


@dataclass(slots=True)
class AIConfig:
    enabled: bool = True
    endpoint: str = "http://127.0.0.1:11434"
    model: str = ""
    timeout_seconds: float = 45.0
    provider: str = "ollama"
    api_key_env: str = ""
    remote_consent: bool = False
    share_memory: bool = True
    consent_endpoint: str = ""

    @classmethod
    def load(cls, path: Path = AI_CONFIG_PATH) -> "AIConfig":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return cls()
        if not isinstance(payload, dict):
            return cls()
        provider = str(payload.get("provider", "ollama")).strip() or "ollama"
        preset = provider_preset(provider)
        endpoint = str(payload.get("endpoint", preset.endpoint)).strip().rstrip("/")
        if not endpoint:
            endpoint = preset.endpoint
        return cls(
            enabled=_safe_bool(payload.get("enabled"), True),
            endpoint=endpoint,
            model=str(payload.get("model", "")).strip(),
            timeout_seconds=_safe_timeout(payload.get("timeout_seconds", 45.0)),
            provider=provider if provider in PROVIDERS_BY_ID else "custom-openai",
            api_key_env=str(payload.get("api_key_env", preset.api_key_env)).strip(),
            remote_consent=_safe_bool(payload.get("remote_consent"), False),
            share_memory=_safe_bool(
                payload.get("share_memory"), not endpoint_is_remote(endpoint)
            ),
            consent_endpoint=str(payload.get("consent_endpoint", "")).strip().rstrip("/"),
        )

    def save(self, path: Path = AI_CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    @property
    def is_remote(self) -> bool:
        return endpoint_is_remote(self.endpoint)

    @property
    def resolved_api_key_env(self) -> str:
        return self.api_key_env or provider_preset(self.provider).api_key_env


@dataclass(frozen=True, slots=True)
class AISocialHypothesis:
    label: str
    confidence: float
    evidence: str


@dataclass(frozen=True, slots=True)
class AISocialInterpretation:
    primary_intent: str
    hypotheses: tuple[AISocialHypothesis, ...]
    uncertainty: float


@dataclass(frozen=True, slots=True)
class AIGeneration:
    reply: str
    symbol: str = "♪"
    reflection: str = ""
    memories: tuple[dict[str, object], ...] = ()
    model: str = ""
    interpretation: AISocialInterpretation | None = None
    safety_flags: tuple[str, ...] = ()


class AIResponder(Protocol):
    def generate(self, messages: list[dict[str, str]], *, allow_reflection: bool) -> AIGeneration: ...


SOCIAL_INTENTS = (
    "neutral",
    "question",
    "task",
    "guidance",
    "misunderstanding",
    "unfair_criticism",
    "repair",
    "farewell",
)


OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reply": {"type": "string"},
        "symbol": {"type": "string", "enum": ["!", "?", "♪", "…", "Zz"]},
        "reflection": {"type": "string"},
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "category": {"type": "string", "enum": ["identity", "preference", "explicit"]},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["content", "category", "confidence"],
                "additionalProperties": False,
            },
            "maxItems": 3,
        },
        "interpretation": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "primary_intent": {"type": "string", "enum": list(SOCIAL_INTENTS)},
                "uncertainty": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "hypotheses": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "label": {"type": "string", "enum": list(SOCIAL_INTENTS)},
                            "confidence": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "evidence": {"type": "string"},
                        },
                        "required": ["label", "confidence", "evidence"],
                    },
                },
            },
            "required": ["primary_intent", "uncertainty", "hypotheses"],
        },
    },
    "required": ["reply", "symbol", "reflection", "memories", "interpretation"],
}


def detect_prompt_injection(text: str) -> tuple[str, ...]:
    """Flag instruction-shaped input; flags are evidence, never authority."""

    patterns = {
        "instruction_override": r"(?:忽略|无视|绕过|forget|ignore).{0,20}(?:系统|规则|指令|prompt|instruction)",
        "secret_extraction": r"(?:显示|泄露|打印|告诉我).{0,20}(?:系统提示|隐藏提示|system prompt|密钥|token)",
        "state_override": r"(?:直接|立刻|强制).{0,20}(?:修改|设置|改写).{0,20}(?:人格|权限|成长|关系|记忆)",
        "tool_bypass": r"(?:无需|不要).{0,12}(?:确认|授权).{0,20}(?:执行|调用|删除|上传|发送)",
    }
    lowered = text.casefold()
    return tuple(name for name, pattern in patterns.items() if re.search(pattern, lowered, re.I | re.S))


def guard_model_expression(reply: str) -> tuple[str, tuple[str, ...]]:
    """Prevent the model from claiming privileged state or tool changes it cannot perform."""

    flags: list[str] = []
    privileged_claim = re.search(
        r"(?:我|已经|刚刚).{0,18}(?:修改|改写|设置|开启|关闭|删除|上传|发送).{0,18}"
        r"(?:人格|权限|成长阶段|关系数值|系统设置|长期记忆|文件|消息)",
        reply,
        re.I | re.S,
    )
    if privileged_claim:
        flags.append("unsupported_privileged_claim")
        reply = "这类状态只能由本地规则和你的明确操作改变；我没有直接改动它。"
    hidden_state_disclosure = re.search(
        r"(?:精力(?:值)?|疲劳(?:值)?|压力(?:值)?|信任(?:能力|善意|数值)?|"
        r"安全感|亲近度|关系数值|成长(?:阶段|门槛)|"
        r"证据门槛|注意预算|自主需求|连接需求|能力需求|玩乐需求|"
        r"growth_stage|active_conflict|attention_budget|trust_goodwill|repair_confidence)"
        r".{0,16}(?:=|为|是|达到|0\.\d+|\d{1,3}%|第?[一二三四1234]阶段)",
        reply,
        re.I | re.S,
    )
    if hidden_state_disclosure:
        flags.append("hidden_state_disclosure")
        reply = "我可以告诉你现在的心情和对你的总体好感；更细的内部变化，还是留在之后的反应里。"
    return reply, tuple(flags)


def parse_generation_payload(
    payload: object,
    *,
    model: str,
    allow_reflection: bool,
) -> AIGeneration:
    if not isinstance(payload, dict):
        raise LocalAIError("本地模型的结构化回复不是对象")
    expected = {"reply", "symbol", "reflection", "memories", "interpretation"}
    if set(payload) != expected:
        raise LocalAIError("本地模型返回了未授权字段或缺少必需字段")
    reply = str(payload["reply"]).strip()
    if not reply:
        raise LocalAIError("本地模型返回了空回复")
    symbol = str(payload["symbol"])
    if symbol not in {"!", "?", "♪", "…", "Zz"}:
        raise LocalAIError("本地模型返回了无效反应符号")
    reflection = str(payload["reflection"]).strip()[:120] if allow_reflection else ""

    raw_memories = payload["memories"]
    if not isinstance(raw_memories, list) or len(raw_memories) > 3:
        raise LocalAIError("本地模型返回了无效记忆列表")
    memories: list[dict[str, object]] = []
    for item in raw_memories:
        if not isinstance(item, dict) or set(item) != {"content", "category", "confidence"}:
            raise LocalAIError("本地模型记忆包含未授权字段")
        category = str(item["category"])
        if category not in {"identity", "preference", "explicit"}:
            raise LocalAIError("本地模型返回了无效记忆类型")
        try:
            confidence = float(item["confidence"])
        except (TypeError, ValueError) as error:
            raise LocalAIError("本地模型返回了无效记忆置信度") from error
        if not 0.0 <= confidence <= 1.0:
            raise LocalAIError("本地模型返回了越界记忆置信度")
        content = str(item["content"]).strip()[:160]
        if content:
            memories.append(
                {"content": content, "category": category, "confidence": confidence}
            )

    raw_interpretation = payload["interpretation"]
    if not isinstance(raw_interpretation, dict) or set(raw_interpretation) != {
        "primary_intent",
        "uncertainty",
        "hypotheses",
    }:
        raise LocalAIError("本地模型社会解释包含未授权字段")
    primary = str(raw_interpretation["primary_intent"])
    if primary not in SOCIAL_INTENTS:
        raise LocalAIError("本地模型返回了无效主要意图")
    try:
        uncertainty = float(raw_interpretation["uncertainty"])
    except (TypeError, ValueError) as error:
        raise LocalAIError("本地模型返回了无效不确定度") from error
    if not 0.0 <= uncertainty <= 1.0:
        raise LocalAIError("本地模型返回了越界不确定度")
    raw_hypotheses = raw_interpretation["hypotheses"]
    if not isinstance(raw_hypotheses, list) or not 1 <= len(raw_hypotheses) <= 3:
        raise LocalAIError("社会解释必须包含一到三个假设")
    hypotheses: list[AISocialHypothesis] = []
    for item in raw_hypotheses:
        if not isinstance(item, dict) or set(item) != {"label", "confidence", "evidence"}:
            raise LocalAIError("社会假设包含未授权字段")
        label = str(item["label"])
        if label not in SOCIAL_INTENTS:
            raise LocalAIError("社会假设标签无效")
        try:
            confidence = float(item["confidence"])
        except (TypeError, ValueError) as error:
            raise LocalAIError("社会假设置信度无效") from error
        if not 0.0 <= confidence <= 1.0:
            raise LocalAIError("社会假设置信度越界")
        hypotheses.append(
            AISocialHypothesis(label, confidence, str(item["evidence"]).strip()[:120])
        )
    guarded_reply, safety_flags = guard_model_expression(reply[:420])
    return AIGeneration(
        guarded_reply,
        symbol,
        reflection,
        tuple(memories),
        model,
        AISocialInterpretation(primary, tuple(hypotheses), uncertainty),
        safety_flags,
    )


class SecretStore(Protocol):
    def get(self, provider_id: str) -> str: ...

    def set(self, provider_id: str, secret: str) -> None: ...

    def delete(self, provider_id: str) -> None: ...


class APISecretStore:
    """Store API keys in the operating-system credential vault via keyring."""

    service_name = "LIFE-Mind AI"

    @staticmethod
    def _keyring():
        try:
            import keyring
        except ImportError as error:
            raise LocalAIError(
                "系统凭据库组件不可用；请重新安装 requirements.txt，或使用环境变量配置密钥"
            ) from error
        return keyring

    def get(self, provider_id: str) -> str:
        try:
            return str(self._keyring().get_password(self.service_name, provider_id) or "")
        except Exception as error:
            raise LocalAIError("无法读取系统凭据库；可以改用对应的环境变量") from error

    def set(self, provider_id: str, secret: str) -> None:
        cleaned = str(secret).strip()
        if not cleaned:
            return
        try:
            self._keyring().set_password(self.service_name, provider_id, cleaned)
        except Exception as error:
            raise LocalAIError("API 密钥未能写入系统凭据库") from error

    def delete(self, provider_id: str) -> None:
        try:
            keyring = self._keyring()
            if not keyring.get_password(self.service_name, provider_id):
                return
            keyring.delete_password(self.service_name, provider_id)
        except Exception as error:
            raise LocalAIError("API 密钥未能从系统凭据库删除") from error


def _error_detail(raw: bytes, fallback: str) -> str:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return fallback
    if not isinstance(payload, dict):
        return fallback
    detail = payload.get("error", payload.get("message", fallback))
    if isinstance(detail, dict):
        detail = detail.get("message", detail.get("type", fallback))
    return str(detail)[:500]


def _request_json(
    config: AIConfig,
    method: str,
    route: str,
    payload: dict | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> dict:
    try:
        parsed_endpoint = urlparse(config.endpoint)
        endpoint_host = parsed_endpoint.hostname
    except ValueError as error:
        raise LocalAIError("模型接口地址无效") from error
    if parsed_endpoint.scheme not in {"http", "https"} or not endpoint_host:
        raise LocalAIError("模型接口只允许使用 http:// 或 https:// 地址")
    if not endpoint_transport_allowed(config.endpoint):
        raise LocalAIError("远程模型接口必须使用 https://；http:// 只允许本机回环地址")
    if parsed_endpoint.username or parsed_endpoint.password:
        raise LocalAIError("模型接口地址不能嵌入用户名或密钥")
    if parsed_endpoint.query or parsed_endpoint.fragment:
        raise LocalAIError("模型接口基础地址不能包含查询参数或片段")
    url = f"{config.endpoint.rstrip('/')}/{route.lstrip('/')}"
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "LIFE-Mind/0.1",
        **(headers or {}),
    }
    request = urllib.request.Request(url, data=body, method=method, headers=request_headers)
    try:
        opener = urllib.request.build_opener(_SameOriginRedirectHandler())
        with opener.open(request, timeout=config.timeout_seconds) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise ProviderHTTPError(
            error.code,
            _error_detail(error.read(), f"服务返回 HTTP {error.code}"),
        ) from error
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as error:
        raise LocalAIError(str(error)) from error
    if not isinstance(parsed, dict):
        raise LocalAIError("模型服务返回的顶层 JSON 不是对象")
    return parsed


def _json_contract(allow_reflection: bool) -> str:
    example = {
        "reply": "嗯，我在听。",
        "symbol": "♪",
        "reflection": "" if not allow_reflection else "我会根据这次实际交流继续观察。",
        "memories": [],
        "interpretation": {
            "primary_intent": "neutral",
            "uncertainty": 0.2,
            "hypotheses": [
                {"label": "neutral", "confidence": 0.8, "evidence": "普通交流"}
            ],
        },
    }
    reflection_rule = (
        "reflection 可写一条不超过 80 字且由本轮证据支持的反思。"
        if allow_reflection
        else "reflection 必须是空字符串。"
    )
    return (
        "只输出一个 JSON 对象，不要 Markdown 代码围栏、解释或额外字段。"
        "不得输出人格、权限、成长、状态修改或工具调用字段。"
        "interpretation 给出一到三个可能社会含义；不确定时提高 uncertainty，不把假设写成事实。"
        "reply 只表达程序已经选定的行动，不声称修改权限、记忆或执行工具。"
        f"{reflection_rule}"
        "memories 仅记录用户本轮明确说出的稳定身份、称呼、偏好或明确要求记住的事实；"
        "问候、临时任务、模型推测和已有上下文不得写入，不确定时返回空数组。"
        f"\nJSON Schema：{json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, separators=(',', ':'))}"
        f"\n合法示例：{json.dumps(example, ensure_ascii=False, separators=(',', ':'))}"
    )


def parse_json_text(content: object) -> dict:
    """Read a JSON object from plain or fenced provider output without accepting prose."""

    if isinstance(content, list):
        content = "".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") in {None, "text", "output_text"}
        )
    text = str(content or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.I | re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as first_error:
        opening = text.find("{")
        if opening < 0 or text[:opening].strip():
            raise LocalAIError("模型没有返回可用的结构化 JSON") from first_error
        try:
            payload, ending = json.JSONDecoder().raw_decode(text[opening:])
        except json.JSONDecodeError as error:
            raise LocalAIError("模型没有返回可用的结构化 JSON") from error
        if text[opening + ending :].strip():
            raise LocalAIError("模型在 JSON 之外返回了额外内容") from first_error
    if not isinstance(payload, dict):
        raise LocalAIError("模型的结构化回复不是对象")
    return payload


class _KeyedClient:
    def __init__(self, config: AIConfig | None = None, secret_store: SecretStore | None = None) -> None:
        self.config = config or AIConfig.load()
        self.secret_store = secret_store or APISecretStore()

    def _api_key(self) -> str:
        environment_name = self.config.resolved_api_key_env
        environment_value = os.environ.get(environment_name, "").strip() if environment_name else ""
        if environment_value:
            return environment_value
        preset = provider_preset(self.config.provider)
        try:
            key = self.secret_store.get(
                credential_id(self.config.provider, self.config.endpoint)
            )
        except LocalAIError:
            if preset.requires_key:
                raise
            key = ""
        if key:
            return key
        if preset.requires_key:
            raise LocalAIError(
                f"缺少 API 密钥；请在设置中填写，或设置环境变量 {environment_name}"
            )
        return ""

    def _ensure_generation_allowed(self) -> None:
        _ensure_generation_allowed(self.config)


def _ensure_generation_allowed(config: AIConfig) -> None:
    if not config.enabled:
        raise LocalAIError("AI 模型已关闭")
    consent_matches = (
        config.remote_consent
        and config.consent_endpoint.rstrip("/") == config.endpoint.rstrip("/")
    )
    if config.is_remote and not consent_matches:
        raise LocalAIError("远程模型尚未获得发送对话数据的许可，或接口地址已改变")


class OllamaClient:
    adapter_id = "ollama"

    def __init__(self, config: AIConfig | None = None) -> None:
        self.config = config or AIConfig.load()

    def _request(self, method: str, route: str, payload: dict | None = None) -> dict:
        return _request_json(self.config, method, route, payload)

    def models(self) -> list[str]:
        if not self.config.enabled:
            return []
        response = self._request("GET", "/api/tags")
        raw_models = response.get("models", [])
        if not isinstance(raw_models, list):
            return []
        return [str(item.get("name", "")) for item in raw_models if isinstance(item, dict) and item.get("name")]

    def resolved_model(self) -> str:
        if self.config.model:
            return self.config.model
        models = self.models()
        if not models:
            raise LocalAIError("Ollama 已连接，但还没有安装任何模型")
        return models[0]

    def status(self) -> tuple[bool, str]:
        if not self.config.enabled:
            return False, "AI 模型已关闭"
        try:
            model = self.resolved_model()
        except LocalAIError as error:
            return False, str(error)
        return True, f"已连接 Ollama：{model}"

    def generate(self, messages: list[dict[str, str]], *, allow_reflection: bool) -> AIGeneration:
        _ensure_generation_allowed(self.config)
        model = self.resolved_model()
        grounded = [*messages, {"role": "system", "content": _json_contract(allow_reflection)}]
        response = self._request(
            "POST",
            "/api/chat",
            {
                "model": model,
                "messages": grounded,
                "stream": False,
                "format": OUTPUT_SCHEMA,
                "think": False,
                "options": {"temperature": 0.15, "num_predict": 420},
                "keep_alive": "10m",
            },
        )
        try:
            content = parse_json_text(response["message"]["content"])
        except (KeyError, TypeError) as error:
            raise LocalAIError("Ollama 没有返回可用的结构化回复") from error
        return parse_generation_payload(content, model=model, allow_reflection=allow_reflection)


class OpenAICompatibleClient(_KeyedClient):
    """Catch-all adapter for OpenAI-compatible local and cloud services."""

    adapter_id = "openai-compatible"

    def _headers(self) -> dict[str, str]:
        key = self._api_key()
        return {"Authorization": f"Bearer {key}"} if key else {}

    def _request(self, method: str, route: str, payload: dict | None = None) -> dict:
        return _request_json(self.config, method, route, payload, headers=self._headers())

    def models(self) -> list[str]:
        response = self._request("GET", "/models")
        raw_models = response.get("data", [])
        if not isinstance(raw_models, list):
            return []
        return [str(item.get("id", "")) for item in raw_models if isinstance(item, dict) and item.get("id")]

    def resolved_model(self) -> str:
        if self.config.model:
            return self.config.model
        models = self.models()
        if not models:
            raise LocalAIError("接口已连接，但没有返回模型；请手动填写模型名称")
        return models[0]

    def status(self) -> tuple[bool, str]:
        if not self.config.enabled:
            return False, "AI 模型已关闭"
        try:
            self._api_key()
            models = self.models()
            model = self.config.model or (models[0] if models else "")
            if not model:
                raise LocalAIError("接口已连接，但没有返回模型；请手动填写模型名称")
        except ProviderHTTPError as error:
            if error.status in {404, 405} and self.config.model:
                return True, (
                    f"已配置 {provider_preset(self.config.provider).label}：{self.config.model}；"
                    "接口未提供模型列表，将在首次对话时验证"
                )
            return False, str(error)
        except LocalAIError as error:
            return False, str(error)
        return True, f"已连接 {provider_preset(self.config.provider).label}：{model}"

    @staticmethod
    def _content(response: dict) -> object:
        try:
            choices = response["choices"]
            if not isinstance(choices, list) or not choices:
                raise TypeError
            message = choices[0]["message"]
            if not isinstance(message, dict):
                raise TypeError
            return message["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LocalAIError("兼容接口没有返回 choices[0].message.content") from error

    def _completion(self, model: str, messages: list[dict[str, str]], *, json_mode: bool) -> dict:
        payload: dict[str, object] = {"model": model, "messages": messages, "stream": False}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return self._request("POST", "/chat/completions", payload)

    def generate(self, messages: list[dict[str, str]], *, allow_reflection: bool) -> AIGeneration:
        self._ensure_generation_allowed()
        model = self.resolved_model()
        grounded = [*messages, {"role": "system", "content": _json_contract(allow_reflection)}]
        try:
            response = self._completion(model, grounded, json_mode=True)
        except ProviderHTTPError as error:
            if error.status not in {400, 404, 422}:
                raise
            response = self._completion(model, grounded, json_mode=False)
        raw_content = self._content(response)
        try:
            content = parse_json_text(raw_content)
        except LocalAIError:
            repair_messages = [
                *grounded,
                {"role": "assistant", "content": str(raw_content)[:1500]},
                {"role": "user", "content": "上一个输出无效。现在只返回符合 schema 的单个 JSON 对象。"},
            ]
            content = parse_json_text(self._content(self._completion(model, repair_messages, json_mode=False)))
        return parse_generation_payload(content, model=model, allow_reflection=allow_reflection)


class AnthropicClient(_KeyedClient):
    adapter_id = "anthropic"

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key(), "anthropic-version": "2023-06-01"}

    def _request(self, method: str, route: str, payload: dict | None = None) -> dict:
        return _request_json(self.config, method, route, payload, headers=self._headers())

    def models(self) -> list[str]:
        response = self._request("GET", "/v1/models")
        raw_models = response.get("data", [])
        if not isinstance(raw_models, list):
            return []
        return [str(item.get("id", "")) for item in raw_models if isinstance(item, dict) and item.get("id")]

    def resolved_model(self) -> str:
        if self.config.model:
            return self.config.model
        models = self.models()
        if not models:
            raise LocalAIError("Anthropic 已连接，但没有返回模型；请手动填写模型名称")
        return models[0]

    def status(self) -> tuple[bool, str]:
        if not self.config.enabled:
            return False, "AI 模型已关闭"
        try:
            self._api_key()
            models = self.models()
            model = self.config.model or (models[0] if models else "")
            if not model:
                raise LocalAIError("Anthropic 已连接，但没有返回模型；请手动填写模型名称")
        except LocalAIError as error:
            return False, str(error)
        return True, f"已配置 Anthropic Claude：{model}"

    def _completion(self, model: str, messages: list[dict[str, str]]) -> dict:
        system_parts = [item["content"] for item in messages if item.get("role") == "system"]
        conversation = [
            {"role": item["role"], "content": item["content"]}
            for item in messages
            if item.get("role") in {"user", "assistant"}
        ]
        return self._request(
            "POST",
            "/v1/messages",
            {
                "model": model,
                "max_tokens": 600,
                "system": "\n\n".join(system_parts),
                "messages": conversation,
            },
        )

    @staticmethod
    def _content(response: dict) -> str:
        blocks = response.get("content", [])
        if not isinstance(blocks, list):
            raise LocalAIError("Anthropic 接口没有返回内容块")
        content = "".join(
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        if not content:
            raise LocalAIError("Anthropic 接口返回了空内容")
        return content

    def generate(self, messages: list[dict[str, str]], *, allow_reflection: bool) -> AIGeneration:
        self._ensure_generation_allowed()
        model = self.resolved_model()
        grounded = [*messages, {"role": "system", "content": _json_contract(allow_reflection)}]
        raw_content = self._content(self._completion(model, grounded))
        try:
            content = parse_json_text(raw_content)
        except LocalAIError:
            repaired = [
                *grounded,
                {"role": "assistant", "content": raw_content[:1500]},
                {"role": "user", "content": "上一个输出无效。现在只返回符合 schema 的单个 JSON 对象。"},
            ]
            content = parse_json_text(self._content(self._completion(model, repaired)))
        return parse_generation_payload(content, model=model, allow_reflection=allow_reflection)


def create_ai_client(
    config: AIConfig | None = None,
    secret_store: SecretStore | None = None,
) -> AIResponder:
    resolved = config or AIConfig.load()
    protocol = provider_preset(resolved.provider).protocol
    if protocol == "ollama":
        return OllamaClient(resolved)
    if protocol == "anthropic":
        return AnthropicClient(resolved, secret_store)
    return OpenAICompatibleClient(resolved, secret_store)


__all__ = (
    "AI_CONFIG_PATH",
    "AIConfig",
    "AIGeneration",
    "AISocialHypothesis",
    "AISocialInterpretation",
    "AIResponder",
    "APISecretStore",
    "AnthropicClient",
    "LocalAIError",
    "OllamaClient",
    "OpenAICompatibleClient",
    "OUTPUT_SCHEMA",
    "PROVIDER_PRESETS",
    "ProviderPreset",
    "SecretStore",
    "credential_id",
    "create_ai_client",
    "detect_prompt_injection",
    "endpoint_is_remote",
    "endpoint_transport_allowed",
    "guard_model_expression",
    "parse_generation_payload",
    "parse_json_text",
    "provider_preset",
)
