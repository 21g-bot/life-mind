"""Bridges live desktop-pet inputs to deterministic mind events."""

from __future__ import annotations

import uuid

from life_mind.ai import detect_prompt_injection
from life_mind.behavior import DialogueCue
from life_mind.domain import EventType, MindEvent, PrivacyLevel, SimulationTrace


ACTION_CLIPS = {
    "accept_task": "work",
    "report_success": "happy",
    "quietly_continue": "work",
    "negotiate_rest": "sleep",
    "acknowledge_specific_error": "pensive",
    "pause_and_review": "pensive",
    "accept_specific_guidance": "curious",
    "ask_for_clarification": "curious",
    "acknowledge_error_and_set_boundary": "pensive",
    "pause_unsafe_conversation": "pensive",
    "continue_private_life": "idle",
    "warm_welcome": "greet",
    "gentle_reconnect": "greet",
    "rest": "sleep",
    "draw_private": "draw",
    "learn_small_skill": "work",
    "work_private": "work",
    "care_for_plant": "water",
    "observe_room": "look_around",
    "hum_softly": "hum",
    "idle_companion": "idle",
    "record_repair_evidence": "relieved",
    "keep_safe_distance": "pensive",
    "integrate_reflection": "pensive",
}


def new_event_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def action_clip(action: str) -> str:
    return ACTION_CLIPS.get(action, "")


def trace_action_clip(trace: SimulationTrace | dict) -> str:
    selected = trace.selected_action if isinstance(trace, SimulationTrace) else trace.get("selected_action", {})
    return action_clip(str(selected.get("action", "")))


class MindEventBridge:
    """Translate UI intent into evidence-bearing domain events."""

    SUCCESS_PHRASES = ("任务成功", "成功了", "做完了", "完成了", "已经通过")
    FAILURE_PHRASES = ("任务失败", "失败了", "没完成", "出错了", "有遗漏", "搞砸了")

    @staticmethod
    def dialogue(text: str, cue: DialogueCue, *, event_id: str | None = None) -> MindEvent:
        cleaned = text.strip()
        injection_flags = detect_prompt_injection(cleaned)
        metadata: dict[str, object] = {
            "emotion": cue.emotion,
            "reason": cue.reason,
            "prompt_injection_flags": list(injection_flags),
            "program_constraints_enforced": True,
        }
        event_type = EventType.CONVERSATION
        privacy = PrivacyLevel.PRIVATE

        if any(phrase in cleaned for phrase in MindEventBridge.FAILURE_PHRASES):
            event_type = EventType.TASK_FAILURE
        elif any(phrase in cleaned for phrase in MindEventBridge.SUCCESS_PHRASES):
            event_type = EventType.TASK_SUCCESS
        elif cue.intent == "task":
            event_type = EventType.TASK_REQUEST
            metadata.update({"pressure": 0.55, "work_cost": 0.10})
        elif cue.intent == "hostility":
            event_type = EventType.UNFAIR_CRITICISM
            privacy = PrivacyLevel.SENSITIVE
            metadata.update(
                {
                    "content_validity": 0.25,
                    "delivery_acceptability": 0.04,
                    "benign_intent_probability": 0.12,
                }
            )
        elif cue.intent == "misunderstanding":
            event_type = EventType.GUIDANCE
            metadata.update(
                {
                    "content_validity": 0.55,
                    "delivery_acceptability": 0.88,
                    "benign_intent_probability": 0.86,
                    "clarification_requested": True,
                }
            )
        elif cue.intent == "correction":
            event_type = EventType.GUIDANCE
            metadata.update(
                {
                    "content_validity": 0.78,
                    "delivery_acceptability": 0.62,
                    "benign_intent_probability": 0.72,
                }
            )
        elif cue.intent == "farewell":
            event_type = EventType.ABSENCE
            metadata["days"] = 0.0

        return MindEvent(
            event_id=event_id or new_event_id("dialogue"),
            event_type=event_type,
            actor_id="user",
            content=cleaned,
            source="user_input",
            confidence=0.96 if event_type != EventType.CONVERSATION else 0.90,
            privacy=privacy,
            allowed_uses=("state_update", "reflection", "dialogue"),
            metadata=metadata,
        )

    @staticmethod
    def activity(
        activity: str,
        reason: str,
        *,
        event_id: str | None = None,
        context: str = "desktop_idle",
    ) -> MindEvent:
        focus_map = {
            "sleep": "rest",
            "draw": "draw",
            "work": "work",
            "water": "water",
            "look_around": "look_around",
            "hum": "hum",
            "idle": "idle",
        }
        focus = focus_map.get(activity, "rest")
        return MindEvent(
            event_id=event_id or new_event_id("activity"),
            event_type=EventType.AUTONOMOUS_ACTIVITY,
            actor_id="companion",
            content=reason,
            source="autonomy_scheduler",
            confidence=1.0,
            privacy=PrivacyLevel.PRIVATE,
            allowed_uses=("state_update", "reflection", "narrative"),
            metadata={
                "focus_activity": focus,
                "requested_clip": activity,
                "context": context,
                "cost": 0.04,
            },
        )

    @staticmethod
    def reflection(
        content: str,
        *,
        insight: str = "",
        event_id: str | None = None,
    ) -> MindEvent:
        return MindEvent(
            event_id=event_id or new_event_id("reflection"),
            event_type=EventType.REFLECTION,
            actor_id="companion",
            content=content,
            source="validated_reflection",
            confidence=0.78 if insight else 0.55,
            privacy=PrivacyLevel.PRIVATE,
            allowed_uses=("reflection", "narrative"),
            metadata={"insight": insight},
        )


__all__ = (
    "ACTION_CLIPS",
    "MindEventBridge",
    "action_clip",
    "new_event_id",
    "trace_action_clip",
)
