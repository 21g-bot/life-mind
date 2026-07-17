"""Serializable, model-free contracts used by the headless mind simulator.

The desktop UI and an optional language model are adapters around these
contracts.  They are deliberately deterministic and contain no wall-clock
timestamps so the same seed and event stream can be replayed byte-for-byte.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum, IntEnum
from typing import Any


class EventType(str, Enum):
    CONVERSATION = "conversation"
    TASK_REQUEST = "task_request"
    TASK_SUCCESS = "task_success"
    TASK_FAILURE = "task_failure"
    GUIDANCE = "guidance"
    UNFAIR_CRITICISM = "unfair_criticism"
    ABSENCE = "absence"
    RETURN = "return"
    AUTONOMOUS_ACTIVITY = "autonomous_activity"
    REPAIR = "repair"
    REFLECTION = "reflection"


class GrowthStage(IntEnum):
    WORK_DEPENDENT = 1
    CONFLICT_ACCUMULATING = 2
    FAILURE_CRISIS = 3
    INDEPENDENT_VALUE = 4


class PrivacyLevel(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    SENSITIVE = "sensitive"


class MemoryKind(str, Enum):
    EPISODIC = "episodic"
    RELATIONSHIP = "relationship"
    EMOTIONAL = "emotional"
    REFLECTION = "reflection"
    NARRATIVE = "narrative"


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def to_plain(value: Any) -> Any:
    """Convert nested dataclasses and enums into stable JSON-ready values."""

    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return to_plain(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple, set)):
        items = [to_plain(item) for item in value]
        return sorted(items) if isinstance(value, set) else items
    return value


@dataclass(frozen=True, slots=True)
class MindEvent:
    event_id: str
    event_type: EventType
    actor_id: str
    target_id: str = "companion"
    content: str = ""
    source: str = "simulation"
    confidence: float = 1.0
    privacy: PrivacyLevel = PrivacyLevel.PRIVATE
    allowed_uses: tuple[str, ...] = ("state_update", "reflection")
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id cannot be empty")
        if not self.actor_id.strip():
            raise ValueError("actor_id cannot be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not self.allowed_uses:
            raise ValueError("allowed_uses cannot be empty")

    @classmethod
    def from_dict(cls, payload: dict[str, Any], index: int = 0) -> "MindEvent":
        raw_allowed_uses = payload.get("allowed_uses", ("state_update", "reflection"))
        if isinstance(raw_allowed_uses, str):
            raw_allowed_uses = (raw_allowed_uses,)
        return cls(
            event_id=str(payload.get("event_id") or f"event-{index:04d}"),
            event_type=EventType(str(payload["event_type"])),
            actor_id=str(payload.get("actor_id", "user")),
            target_id=str(payload.get("target_id", "companion")),
            content=str(payload.get("content", "")),
            source=str(payload.get("source", "simulation")),
            confidence=float(payload.get("confidence", 1.0)),
            privacy=PrivacyLevel(str(payload.get("privacy", "private"))),
            allowed_uses=tuple(str(item) for item in raw_allowed_uses),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class BodyState:
    energy: float = 0.76
    fatigue: float = 0.22
    stress: float = 0.20
    comfort: float = 0.68

    def normalize(self) -> None:
        self.energy = clamp(self.energy)
        self.fatigue = clamp(self.fatigue)
        self.stress = clamp(self.stress)
        self.comfort = clamp(self.comfort)


@dataclass(slots=True)
class NeedState:
    rest: float = 0.24
    connection: float = 0.34
    autonomy: float = 0.32
    competence: float = 0.36
    play: float = 0.40

    def normalize(self) -> None:
        for name in ("rest", "connection", "autonomy", "competence", "play"):
            setattr(self, name, clamp(getattr(self, name)))


@dataclass(slots=True)
class AttentionState:
    focus_target: str = "environment"
    attention_budget: float = 0.72
    interruption_tolerance: float = 0.58

    def normalize(self) -> None:
        self.attention_budget = clamp(self.attention_budget)
        self.interruption_tolerance = clamp(self.interruption_tolerance)


@dataclass(slots=True)
class AffectState:
    valence: float = 0.18
    arousal: float = 0.30
    dominant_emotion: str = "calm"
    cause: str = "初始状态稳定"
    regulation: float = 0.66

    def normalize(self) -> None:
        self.valence = clamp(self.valence, -1.0, 1.0)
        self.arousal = clamp(self.arousal)
        self.regulation = clamp(self.regulation)


@dataclass(frozen=True, slots=True)
class TemperamentState:
    sensitivity: float = 0.66
    persistence: float = 0.72
    novelty_seeking: float = 0.46
    social_need: float = 0.44


@dataclass(frozen=True, slots=True)
class PersonalityState:
    warmth: float = 0.80
    assertiveness: float = 0.56
    independence: float = 0.42
    discipline: float = 0.72
    resilience: float = 0.60


@dataclass(frozen=True, slots=True)
class ValueState:
    care: float = 0.86
    truth: float = 0.84
    dignity: float = 0.90
    growth: float = 0.82
    responsibility: float = 0.86


@dataclass(slots=True)
class RelationState:
    actor_id: str
    trust_ability: float = 0.55
    trust_goodwill: float = 0.55
    respect: float = 0.60
    safety: float = 0.60
    closeness: float = 0.45
    repair_confidence: float = 0.35
    harm_events: int = 0
    repair_evidence: list[str] = field(default_factory=list)

    def normalize(self) -> None:
        for name in (
            "trust_ability",
            "trust_goodwill",
            "respect",
            "safety",
            "closeness",
            "repair_confidence",
        ):
            setattr(self, name, clamp(getattr(self, name)))


@dataclass(slots=True)
class GrowthState:
    stage: GrowthStage = GrowthStage.WORK_DEPENDENT
    active_conflict: str = "渴望被需要，但价值不应只来自工作"
    awareness_count: int = 0
    overwork_choices: int = 0
    failure_under_fatigue: int = 0
    independent_choices: int = 0
    independent_contexts: list[str] = field(default_factory=list)
    cost_paid: float = 0.0
    aligned_reflections: int = 0
    narrative_chapter: str = "只有工作时才有价值"


@dataclass(slots=True)
class MindState:
    tick: int = 0
    body: BodyState = field(default_factory=BodyState)
    needs: NeedState = field(default_factory=NeedState)
    attention: AttentionState = field(default_factory=AttentionState)
    affect: AffectState = field(default_factory=AffectState)
    temperament: TemperamentState = field(default_factory=TemperamentState)
    personality: PersonalityState = field(default_factory=PersonalityState)
    values: ValueState = field(default_factory=ValueState)
    relations: dict[str, RelationState] = field(default_factory=dict)
    growth: GrowthState = field(default_factory=GrowthState)
    last_action: str = "idle"

    def normalize(self) -> None:
        self.body.normalize()
        self.needs.normalize()
        self.attention.normalize()
        self.affect.normalize()
        for relation in self.relations.values():
            relation.normalize()

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass(frozen=True, slots=True)
class SocialAppraisal:
    content_validity: float
    delivery_acceptability: float
    benign_intent_probability: float
    explanation: str


@dataclass(frozen=True, slots=True)
class ActionCandidate:
    action: str
    proposed_by: tuple[str, ...]
    expected_benefit: float
    relationship_effect: float = 0.0
    interruption_cost: float = 0.0
    risk: float = 0.0
    privacy_cost: float = 0.0
    future_regret: float = 0.0
    explanation: str = ""
    forbidden_reason: str = ""

    def base_score(self) -> float:
        return (
            self.expected_benefit
            + self.relationship_effect * 0.35
            - self.interruption_cost
            - self.risk * 1.20
            - self.privacy_cost
            - self.future_regret * 0.55
        )


@dataclass(frozen=True, slots=True)
class SimMemory:
    memory_id: str
    kind: MemoryKind
    summary: str
    source_event_id: str
    source: str
    confidence: float
    importance: float
    privacy: PrivacyLevel
    allowed_uses: tuple[str, ...]
    review_after_tick: int
    derived_from: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SimulationTrace:
    event: dict[str, Any]
    state_before: dict[str, Any]
    social_appraisal: dict[str, Any]
    candidates: tuple[dict[str, Any], ...]
    selected_action: dict[str, Any]
    state_after: dict[str, Any]
    memory_ids: tuple[str, ...]
    growth_change: str = ""
    notes: tuple[str, ...] = ()
