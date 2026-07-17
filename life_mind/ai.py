"""Local Ollama adapter for LIFE-Mind."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LIFE-Mind"
AI_CONFIG_PATH = DATA_DIR / "ai-config.json"


class LocalAIError(RuntimeError):
    pass


@dataclass(slots=True)
class AIConfig:
    enabled: bool = True
    endpoint: str = "http://127.0.0.1:11434"
    model: str = ""
    timeout_seconds: float = 45.0

    @classmethod
    def load(cls, path: Path = AI_CONFIG_PATH) -> "AIConfig":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return cls()
        return cls(
            enabled=bool(payload.get("enabled", True)),
            endpoint=str(payload.get("endpoint", "http://127.0.0.1:11434")).rstrip("/"),
            model=str(payload.get("model", "")).strip(),
            timeout_seconds=max(2.0, min(180.0, float(payload.get("timeout_seconds", 45.0)))),
        )

    def save(self, path: Path = AI_CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


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


class OllamaClient:
    def __init__(self, config: AIConfig | None = None) -> None:
        self.config = config or AIConfig.load()

    def _request(self, method: str, route: str, payload: dict | None = None) -> dict:
        url = f"{self.config.endpoint.rstrip('/')}{route}"
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read().decode("utf-8")).get("error", str(error))
            except (ValueError, UnicodeDecodeError):
                detail = str(error)
            raise LocalAIError(detail) from error
        except (OSError, urllib.error.URLError, TimeoutError, ValueError) as error:
            raise LocalAIError(str(error)) from error

    def models(self) -> list[str]:
        if not self.config.enabled:
            return []
        response = self._request("GET", "/api/tags")
        return [str(item.get("name", "")) for item in response.get("models", []) if item.get("name")]

    def resolved_model(self) -> str:
        if self.config.model:
            return self.config.model
        models = self.models()
        if not models:
            raise LocalAIError("Ollama 已连接，但还没有安装任何模型")
        return models[0]

    def status(self) -> tuple[bool, str]:
        if not self.config.enabled:
            return False, "本地 AI 已关闭"
        try:
            model = self.resolved_model()
        except LocalAIError as error:
            return False, str(error)
        return True, f"已连接 Ollama：{model}"

    def generate(self, messages: list[dict[str, str]], *, allow_reflection: bool) -> AIGeneration:
        if not self.config.enabled:
            raise LocalAIError("本地 AI 已关闭")
        model = self.resolved_model()
        grounded = list(messages)
        grounded.append(
            {
                "role": "system",
                "content": (
                    "请严格输出给定 JSON schema，不得增加人格、权限、成长、状态修改或工具调用字段。"
                    "interpretation 必须给出一到三个可能社会含义及置信度；不确定时提高 uncertainty，"
                    "不要把假设写成事实。reply 只表达程序已经选定的行动，不声称修改权限或执行工具。"
                    "reflection"
                    + ("可写一条不超过80字、由本轮证据支持的自我反思。" if allow_reflection else "必须为空字符串。")
                    + "memories 只记录用户本轮明确说出的稳定事实、称呼或偏好；不推测隐私，不确定时返回空数组。"
                ),
            }
        )
        response = self._request(
            "POST",
            "/api/chat",
            {
                "model": model,
                "messages": grounded,
                "stream": False,
                "format": OUTPUT_SCHEMA,
                "think": False,
                "options": {"temperature": 0.55, "num_predict": 220},
                "keep_alive": "10m",
            },
        )
        try:
            content = json.loads(response["message"]["content"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise LocalAIError("本地模型没有返回可用的结构化回复") from error
        return parse_generation_payload(
            content,
            model=model,
            allow_reflection=allow_reflection,
        )


__all__ = (
    "AI_CONFIG_PATH",
    "AIConfig",
    "AIGeneration",
    "AISocialHypothesis",
    "AISocialInterpretation",
    "AIResponder",
    "LocalAIError",
    "OllamaClient",
    "OUTPUT_SCHEMA",
    "detect_prompt_injection",
    "guard_model_expression",
    "parse_generation_payload",
)
