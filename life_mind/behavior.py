"""Deterministic affect and autonomy state machine for the desktop pet."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Protocol


class StateSnapshot(Protocol):
    energy: float
    mood: float
    trust: float


@dataclass(frozen=True, slots=True)
class DialogueCue:
    intent: str
    emotion: str
    clip: str
    symbol: str
    duration_ms: int
    mood_delta: float = 0.0
    trust_delta: float = 0.0
    activity: str | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class BehaviorDecision:
    activity: str
    emotion: str
    clip: str
    duration_seconds: float
    reason: str
    priority: int = 10


def classify_dialogue_cue(text: str, symbol: str = "") -> DialogueCue:
    """Convert user language into a bounded, explainable affect signal."""
    normalized = text.strip().lower()
    if any(word in normalized for word in ("废物", "没用", "讨厌你", "滚开", "蠢")):
        return DialogueCue(
            "hostility", "pensive", "pensive", "…", 6200, -0.07, -0.018,
            reason="用户使用了整体否定或敌意表达",
        )
    if any(word in normalized for word in ("你误会了", "不是这个意思", "我不是说", "理解错了")):
        return DialogueCue(
            "misunderstanding", "curious", "curious", "?", 5000, -0.004, 0.003,
            reason="用户指出可能存在理解偏差，需要先澄清",
        )
    if any(word in normalized for word in ("不对", "错了", "不是这样", "不好", "需要改", "重新")):
        return DialogueCue(
            "correction", "pensive", "pensive", "…", 4800, -0.018, 0.002,
            reason="用户指出了具体错误",
        )
    if any(word in normalized for word in ("休息", "别累", "辛苦了", "没关系", "慢慢来", "抱抱")):
        return DialogueCue(
            "care", "relieved", "relieved", "♪", 5000, 0.045, 0.016,
            reason="用户表达关心或允许休息",
        )
    if any(word in normalized for word in ("谢谢", "喜欢你", "可爱", "真棒", "厉害", "乖", "好看")):
        return DialogueCue(
            "praise", "happy", "happy", "♪", 4600, 0.052, 0.012,
            reason="用户表达感谢、喜爱或肯定",
        )
    if any(word in normalized for word in ("帮我", "开始工作", "开始任务", "继续任务", "处理一下", "完成这个")):
        return DialogueCue(
            "task", "focused", "work", "!", 5200, 0.012, 0.004, "work",
            "用户提出了明确任务",
        )
    if any(word in normalized for word in ("再见", "晚安", "我走了", "一会见", "回头见")):
        return DialogueCue(
            "farewell", "tender", "greet", "♪", 5200, 0.008, 0.004,
            reason="用户暂时离开或道别",
        )
    if any(word in normalized for word in ("你好", "早上好", "早安", "晚上好", "在吗", "回来啦")):
        return DialogueCue(
            "greeting", "happy", "greet", "♪", 4200, 0.018, 0.004,
            reason="用户主动打招呼",
        )
    if symbol == "!" or any(word in normalized for word in ("震惊", "居然", "竟然", "天啊", "真的！")):
        return DialogueCue(
            "surprise", "surprised", "surprised", "!", 3600, 0.004, 0.0,
            reason="用户表达了明显惊讶",
        )
    if symbol == "?" or "?" in normalized or "？" in normalized or any(
        word in normalized for word in ("为什么", "怎么", "什么", "哪里", "谁", "吗", "呢")
    ):
        return DialogueCue(
            "question", "curious", "curious", "?", 4600, 0.002, 0.0,
            reason="用户提出问题",
        )
    return DialogueCue(
        "conversation", "calm", "idle", symbol or "♪", 3200, 0.004, 0.001,
        reason="普通对话，保持安静专注",
    )


class BehaviorStateMachine:
    """Choose infrequent, state-grounded reactions and autonomous activities."""

    ACTIVITY_LENGTHS = {
        "draw": (34.0, 58.0),
        "water": (22.0, 38.0),
        "work": (38.0, 65.0),
        "sleep": (42.0, 80.0),
        "look_around": (8.0, 13.0),
        "hum": (12.0, 20.0),
        "idle": (12.0, 24.0),
    }
    ACTIVITY_COOLDOWNS = {
        "draw": 105.0,
        "water": 150.0,
        "work": 120.0,
        "sleep": 135.0,
        "look_around": 55.0,
        "hum": 80.0,
        "idle": 20.0,
    }

    def __init__(self, *, seed: int | None = None, now: float | None = None) -> None:
        self.rng = random.Random(seed)
        current = time.monotonic() if now is None else now
        self.current_activity = "idle"
        self.current_emotion = "calm"
        self.activity_until = current + 16.0
        self.next_decision_at = current + 18.0
        self.last_interaction_at = current
        self.cooldowns: dict[str, float] = {}
        self.last_reason = "启动后先安静待机"

    def on_dialogue(
        self,
        text: str,
        symbol: str,
        state: StateSnapshot,
        *,
        now: float | None = None,
    ) -> tuple[DialogueCue, BehaviorDecision]:
        current = time.monotonic() if now is None else now
        cue = classify_dialogue_cue(text, symbol)
        self.last_interaction_at = current
        self.current_emotion = cue.emotion
        self.next_decision_at = current + 16.0
        if cue.activity:
            self.current_activity = cue.activity
            low, high = self.ACTIVITY_LENGTHS[cue.activity]
            duration = self.rng.uniform(low, high)
            self.activity_until = current + duration
            self.cooldowns[cue.activity] = current + self.ACTIVITY_COOLDOWNS[cue.activity]
        else:
            duration = cue.duration_ms / 1000.0
            self.current_activity = "idle"
            self.activity_until = current + duration
        self.last_reason = cue.reason
        return cue, BehaviorDecision(
            cue.activity or self.current_activity,
            cue.emotion,
            cue.clip,
            duration,
            cue.reason,
            priority=90,
        )

    def set_manual_activity(self, activity: str, *, now: float | None = None) -> BehaviorDecision:
        current = time.monotonic() if now is None else now
        if activity == "idle":
            duration = 18.0
            emotion = "calm"
        else:
            low, high = self.ACTIVITY_LENGTHS.get(activity, (24.0, 45.0))
            duration = self.rng.uniform(low, high)
            emotion = "tired" if activity == "sleep" else "focused"
        self.current_activity = activity
        self.current_emotion = emotion
        self.activity_until = current + duration
        self.next_decision_at = self.activity_until + 12.0
        self.cooldowns[activity] = current + self.ACTIVITY_COOLDOWNS.get(activity, 60.0)
        self.last_reason = "用户从动作菜单中主动选择"
        return BehaviorDecision(activity, emotion, activity, duration, self.last_reason, 100)

    def tick(self, state: StateSnapshot, *, now: float | None = None) -> BehaviorDecision | None:
        current = time.monotonic() if now is None else now
        if current < self.next_decision_at:
            return None
        if self.current_activity != "idle" and current < self.activity_until:
            self.next_decision_at = min(self.activity_until, current + 8.0)
            return None
        if current - self.last_interaction_at < 14.0:
            self.next_decision_at = current + 8.0
            return None

        if self.current_activity != "idle":
            self.current_activity = "idle"
            self.current_emotion = self._emotion_from_state(state)
            self.next_decision_at = current + self.rng.uniform(14.0, 22.0)
            self.last_reason = "上一项活动自然结束，先回到待机"
            return BehaviorDecision("idle", self.current_emotion, "idle", 16.0, self.last_reason)

        candidates = self._candidate_weights(state)
        available = [
            (activity, weight)
            for activity, weight in candidates
            if current >= self.cooldowns.get(activity, 0.0)
        ] or [("idle", 1.0)]
        activity = self.rng.choices(
            [item[0] for item in available], weights=[item[1] for item in available], k=1
        )[0]
        low, high = self.ACTIVITY_LENGTHS[activity]
        duration = self.rng.uniform(low, high)
        self.current_activity = activity
        self.current_emotion = self._emotion_from_state(state)
        self.activity_until = current + duration
        self.next_decision_at = current + min(duration, 10.0)
        self.cooldowns[activity] = current + self.ACTIVITY_COOLDOWNS[activity]
        reason = self._reason_for(activity, state)
        self.last_reason = reason
        return BehaviorDecision(activity, self.current_emotion, activity, duration, reason)

    @staticmethod
    def _emotion_from_state(state: StateSnapshot) -> str:
        if state.energy < 0.28:
            return "tired"
        if state.mood < 0.38:
            return "pensive"
        if state.mood > 0.80:
            return "happy"
        return "calm"

    @staticmethod
    def _candidate_weights(state: StateSnapshot) -> list[tuple[str, float]]:
        if state.energy < 0.28:
            return [("sleep", 8.0), ("idle", 2.0), ("draw", 0.8)]
        if state.mood < 0.38:
            return [("draw", 4.0), ("idle", 3.0), ("sleep", 2.0), ("look_around", 0.8)]
        if state.energy < 0.52:
            return [("draw", 3.0), ("sleep", 2.8), ("idle", 2.4), ("water", 1.2)]
        if state.mood > 0.80:
            return [("hum", 3.6), ("water", 2.8), ("draw", 2.4), ("look_around", 1.8)]
        return [("draw", 2.5), ("water", 2.0), ("look_around", 2.0), ("idle", 2.2), ("work", 1.1)]

    @staticmethod
    def _reason_for(activity: str, state: StateSnapshot) -> str:
        reasons = {
            "sleep": "精力偏低，选择坐下休息恢复",
            "draw": "当前没有紧急互动，用画画调节心情",
            "water": "精力与心情稳定，照料桌边的小植物",
            "work": "状态较稳定，安静练习和整理自己的小项目",
            "look_around": "长时间没有新事件，短暂观察周围后继续待机",
            "hum": "心情明亮且精力充足，轻轻哼唱一小会儿",
            "idle": "没有更强需求，保持低打扰陪伴",
        }
        return reasons[activity]


__all__ = (
    "BehaviorDecision",
    "BehaviorStateMachine",
    "DialogueCue",
    "classify_dialogue_cue",
)
