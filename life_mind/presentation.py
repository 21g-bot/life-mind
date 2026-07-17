"""Host-neutral compression from mind decisions to readable pet behaviour.

The mind can keep rich private state, while a renderer receives only this
small, stable vocabulary.  This prevents every host from reverse-engineering
internal variables or inventing its own personality logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from life_mind.domain import SimulationTrace
from life_mind.integration import action_clip


CLIP_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
ALLOWED_SYMBOLS = frozenset({"", "!", "?", "♪", "…", "Zz"})


class PetState(str, Enum):
    """Small public vocabulary shared by Sprite, Live2D, Spine or hardware hosts."""

    SLEEP = "sleep"
    IDLE = "idle"
    BUSY = "busy"
    ATTENTION = "attention"
    CELEBRATE = "celebrate"
    PENSIVE = "pensive"
    CONNECT = "connect"
    PRIVATE_LIFE = "private_life"


@dataclass(frozen=True, slots=True)
class RendererCapabilities:
    renderer_id: str
    supported_clips: tuple[str, ...]
    supports_symbols: bool = True
    max_fps: int = 30

    def __post_init__(self) -> None:
        if (
            not isinstance(self.renderer_id, str)
            or self.renderer_id != self.renderer_id.strip()
            or not CLIP_ID.fullmatch(self.renderer_id)
        ):
            raise ValueError("renderer_id must be a lowercase identifier")
        if not isinstance(self.supported_clips, tuple):
            raise ValueError("supported_clips must be a tuple")
        if not self.supported_clips or "idle" not in self.supported_clips:
            raise ValueError("a renderer must provide an idle fallback clip")
        if len(set(self.supported_clips)) != len(self.supported_clips):
            raise ValueError("supported_clips cannot contain duplicates")
        if any(
            not isinstance(clip, str) or not CLIP_ID.fullmatch(clip)
            for clip in self.supported_clips
        ):
            raise ValueError("supported_clips contains an invalid clip id")
        if not isinstance(self.supports_symbols, bool):
            raise ValueError("supports_symbols must be a boolean")
        if (
            isinstance(self.max_fps, bool)
            or not isinstance(self.max_fps, int)
            or not 1 <= self.max_fps <= 240
        ):
            raise ValueError("max_fps must be between 1 and 240")

    def resolve_clip(self, requested: str) -> str:
        return requested if requested in self.supported_clips else "idle"


@dataclass(frozen=True, slots=True)
class PresentationIntent:
    """Black-box-safe output that any Pet Host can render."""

    state: PetState
    clip: str
    symbol: str = ""
    text: str = ""
    priority: int = 10
    duration_ms: int = 4000
    interruptible: bool = True
    source_event_id: str = ""
    reason_code: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.state, PetState):
            raise ValueError("state must be a PetState")
        if not isinstance(self.clip, str) or not CLIP_ID.fullmatch(self.clip):
            raise ValueError("clip must be a lowercase identifier")
        if not isinstance(self.symbol, str) or self.symbol not in ALLOWED_SYMBOLS:
            raise ValueError("unsupported presentation symbol")
        if not isinstance(self.text, str) or len(self.text) > 160:
            raise ValueError("presentation text cannot exceed 160 characters")
        if (
            isinstance(self.priority, bool)
            or not isinstance(self.priority, int)
            or not 0 <= self.priority <= 100
        ):
            raise ValueError("priority must be between 0 and 100")
        if (
            isinstance(self.duration_ms, bool)
            or not isinstance(self.duration_ms, int)
            or not 250 <= self.duration_ms <= 120_000
        ):
            raise ValueError("duration_ms must be between 250 and 120000")
        if not isinstance(self.interruptible, bool):
            raise ValueError("interruptible must be a boolean")
        if (
            not isinstance(self.source_event_id, str)
            or not isinstance(self.reason_code, str)
            or len(self.source_event_id) > 160
            or len(self.reason_code) > 80
        ):
            raise ValueError("presentation provenance is too long")

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "clip": self.clip,
            "symbol": self.symbol,
            "text": self.text,
            "priority": self.priority,
            "durationMs": self.duration_ms,
            "interruptible": self.interruptible,
            "sourceEventId": self.source_event_id,
            "reasonCode": self.reason_code,
        }


STATE_BY_ACTION = {
    "accept_task": PetState.BUSY,
    "quietly_continue": PetState.BUSY,
    "work_private": PetState.PRIVATE_LIFE,
    "learn_small_skill": PetState.PRIVATE_LIFE,
    "draw_private": PetState.PRIVATE_LIFE,
    "care_for_plant": PetState.PRIVATE_LIFE,
    "observe_room": PetState.PRIVATE_LIFE,
    "hum_softly": PetState.PRIVATE_LIFE,
    "rest": PetState.SLEEP,
    "negotiate_rest": PetState.SLEEP,
    "report_success": PetState.CELEBRATE,
    "ask_for_clarification": PetState.ATTENTION,
    "warm_welcome": PetState.CONNECT,
    "gentle_reconnect": PetState.CONNECT,
    "record_repair_evidence": PetState.CONNECT,
    "acknowledge_specific_error": PetState.PENSIVE,
    "pause_and_review": PetState.PENSIVE,
    "acknowledge_error_and_set_boundary": PetState.PENSIVE,
    "pause_unsafe_conversation": PetState.PENSIVE,
    "keep_safe_distance": PetState.PENSIVE,
    "integrate_reflection": PetState.PENSIVE,
}

SYMBOL_BY_STATE = {
    PetState.SLEEP: "Zz",
    PetState.ATTENTION: "?",
    PetState.CELEBRATE: "!",
    PetState.PENSIVE: "…",
    PetState.CONNECT: "♪",
}

DURATION_BY_STATE = {
    PetState.SLEEP: 8_000,
    PetState.IDLE: 4_000,
    PetState.BUSY: 6_000,
    PetState.ATTENTION: 5_000,
    PetState.CELEBRATE: 4_500,
    PetState.PENSIVE: 6_000,
    PetState.CONNECT: 5_000,
    PetState.PRIVATE_LIFE: 7_000,
}


def _trace_parts(trace: SimulationTrace | Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(trace, SimulationTrace):
        return dict(trace.event), dict(trace.selected_action)
    event = trace.get("event", {})
    selected = trace.get("selected_action", {})
    if not isinstance(event, Mapping) or not isinstance(selected, Mapping):
        raise ValueError("trace event and selected_action must be objects")
    return dict(event), dict(selected)


def project_trace(
    trace: SimulationTrace | Mapping[str, Any],
    capabilities: RendererCapabilities,
    *,
    text: str = "",
) -> PresentationIntent:
    """Project a private decision trace into a renderer-safe public intent."""

    event, selected = _trace_parts(trace)
    action = str(selected.get("action", "idle_companion"))
    state = STATE_BY_ACTION.get(action, PetState.IDLE)
    requested_clip = action_clip(action) or "idle"
    symbol = SYMBOL_BY_STATE.get(state, "") if capabilities.supports_symbols else ""
    priority = 80 if state in {PetState.ATTENTION, PetState.CELEBRATE} else 30
    if state in {PetState.PENSIVE, PetState.SLEEP}:
        priority = 45
    return PresentationIntent(
        state=state,
        clip=capabilities.resolve_clip(requested_clip),
        symbol=symbol,
        text=text.strip(),
        priority=priority,
        duration_ms=DURATION_BY_STATE[state],
        interruptible=state not in {PetState.ATTENTION},
        source_event_id=str(event.get("event_id", "")),
        reason_code=action,
    )


__all__ = (
    "ALLOWED_SYMBOLS",
    "PetState",
    "PresentationIntent",
    "RendererCapabilities",
    "project_trace",
)
