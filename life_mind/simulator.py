"""Deterministic, headless LIFE-Mind simulator.

Run the reference growth arc with::

    python -m life_mind.simulator --repeat 30

The simulator never calls a language model.  It exists to prove that state,
relationships, boundaries and growth remain explainable when AI is offline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from life_mind.domain import (
    ActionCandidate,
    EventType,
    GrowthStage,
    MemoryKind,
    MindEvent,
    MindState,
    PrivacyLevel,
    RelationState,
    SimMemory,
    SimulationTrace,
    SocialAppraisal,
    to_plain,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIO = PROJECT_ROOT / "simulations" / "demo_growth.json"


def bounded(value: Any, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


@dataclass(frozen=True, slots=True)
class SimulationReport:
    seed: int
    scenario: str
    final_state: dict[str, Any]
    traces: tuple[dict[str, Any], ...]
    memories: tuple[dict[str, Any], ...]
    digest: str

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


class HeadlessMindSimulator:
    """Event-sourced mind core with fixed-seed, bounded action choice."""

    REPAIR_REQUIREMENTS = {
        "acknowledgment",
        "responsibility",
        "remedy",
        "changed_behavior",
        "time_evidence",
    }

    def __init__(self, seed: int = 20260717) -> None:
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.state = MindState(
            relations={
                "user": RelationState(
                    "user", 0.62, 0.68, 0.72, 0.70, 0.60, 0.50
                ),
                "guide": RelationState(
                    "guide", 0.76, 0.78, 0.82, 0.80, 0.46, 0.58
                ),
                "critic": RelationState(
                    "critic", 0.48, 0.38, 0.42, 0.42, 0.18, 0.22
                ),
            }
        )
        self.memories: list[SimMemory] = []
        self.traces: list[SimulationTrace] = []

    def ensure_relation(self, actor_id: str) -> RelationState:
        if actor_id not in self.state.relations:
            self.state.relations[actor_id] = RelationState(actor_id)
        return self.state.relations[actor_id]

    def apply_event(self, event: MindEvent) -> SimulationTrace:
        before = deepcopy(self.state.to_dict())
        self.state.tick += 1
        self._passive_tick()
        relation = (
            RelationState(event.actor_id)
            if event.actor_id == event.target_id
            else self.ensure_relation(event.actor_id)
        )
        appraisal = self._appraise(event)
        candidates = self._propose_actions(event, appraisal)
        selected, candidate_trace = self._choose_action(event, candidates)
        notes = self._apply_event_effects(event, appraisal, selected, relation)
        memory_ids = [self._remember_event(event, appraisal)]
        growth_change = self._advance_growth()
        if growth_change:
            memory_ids.append(self._remember_growth(event, growth_change))
        self.state.last_action = selected.action
        self.state.normalize()
        trace = SimulationTrace(
            event=to_plain(event),
            state_before=before,
            social_appraisal=to_plain(appraisal),
            candidates=tuple(candidate_trace),
            selected_action={
                **to_plain(selected),
                "score": next(
                    item["score"] for item in candidate_trace if item["action"] == selected.action
                ),
            },
            state_after=deepcopy(self.state.to_dict()),
            memory_ids=tuple(memory_ids),
            growth_change=growth_change,
            notes=tuple(notes),
        )
        self.traces.append(trace)
        return trace

    def run(self, events: Iterable[MindEvent]) -> tuple[SimulationTrace, ...]:
        for event in events:
            self.apply_event(event)
        return tuple(self.traces)

    def report(self, scenario: str = "custom") -> SimulationReport:
        payload = {
            "seed": self.seed,
            "scenario": scenario,
            "final_state": self.state.to_dict(),
            "traces": [to_plain(trace) for trace in self.traces],
            "memories": [to_plain(memory) for memory in self.memories],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return SimulationReport(
            seed=self.seed,
            scenario=scenario,
            final_state=payload["final_state"],
            traces=tuple(payload["traces"]),
            memories=tuple(payload["memories"]),
            digest=digest,
        )

    def _passive_tick(self) -> None:
        self.state.body.energy -= 0.004
        self.state.body.fatigue += 0.003
        self.state.needs.rest += 0.004
        self.state.attention.attention_budget += 0.01

    def _appraise(self, event: MindEvent) -> SocialAppraisal:
        meta = event.metadata
        if event.event_type == EventType.UNFAIR_CRITICISM:
            return SocialAppraisal(
                bounded(meta.get("content_validity", 0.62)),
                bounded(meta.get("delivery_acceptability", 0.06)),
                bounded(meta.get("benign_intent_probability", 0.24)),
                "批评可能包含具体事实，但人格羞辱和攻击性表达不可接受",
            )
        if event.event_type == EventType.GUIDANCE:
            return SocialAppraisal(
                bounded(meta.get("content_validity", 0.84)),
                bounded(meta.get("delivery_acceptability", 0.88)),
                bounded(meta.get("benign_intent_probability", 0.86)),
                "具体指导的内容、表达和帮助意图分别评价",
            )
        if event.event_type == EventType.TASK_FAILURE:
            return SocialAppraisal(0.95, 0.82, 0.72, "承认具体错误，但不把错误升级为人格结论")
        if event.event_type == EventType.REPAIR:
            return SocialAppraisal(0.70, 0.82, 0.70, "修复按行为证据累计，不因一句道歉恢复信任")
        if event.event_type == EventType.RETURN:
            return SocialAppraisal(1.0, 1.0, 0.95, "用户回来是新的连接机会，不产生忠诚债务")
        return SocialAppraisal(0.90, 0.90, 0.82, "普通事件，按明确内容和已知来源处理")

    def _propose_actions(
        self, event: MindEvent, appraisal: SocialAppraisal
    ) -> list[ActionCandidate]:
        fatigue = self.state.body.fatigue
        stress = self.state.body.stress
        if event.event_type == EventType.CONVERSATION:
            return [
                ActionCandidate(
                    "respond_warmly", ("value.care", "need.connection"), 0.72, 0.06,
                    explanation="回应当前对话，同时保持低打扰陪伴",
                ),
                ActionCandidate(
                    "listen_quietly", ("value.care", "attention.user"), 0.67, 0.04,
                    explanation="在没有明确任务时安静听完，不抢夺话题",
                ),
            ]
        if event.event_type == EventType.TASK_REQUEST:
            pressure = float(event.metadata.get("pressure", 0.5))
            return [
                ActionCandidate(
                    "accept_task",
                    ("value.responsibility", "identity.work_value"),
                    0.72 + pressure * 0.12,
                    relationship_effect=0.10,
                    risk=fatigue * 0.55 + stress * 0.25,
                    future_regret=fatigue * 0.25,
                    explanation="愿意负责，但必须计入疲劳和过度工作代价",
                ),
                ActionCandidate(
                    "negotiate_rest",
                    ("need.rest", "value.dignity", "identity.private_self"),
                    0.48 + self.state.needs.rest * 0.35,
                    relationship_effect=-0.03,
                    interruption_cost=0.05,
                    future_regret=0.02,
                    explanation="精力不足时协商范围或先休息，不把拒绝等同于失去价值",
                ),
            ]
        if event.event_type == EventType.TASK_SUCCESS:
            return [
                ActionCandidate(
                    "report_success", ("value.responsibility",), 0.78, 0.12,
                    explanation="如实汇报结果并保留恢复时间",
                ),
                ActionCandidate(
                    "quietly_continue", ("habit.work",), 0.42, 0.02, future_regret=0.12,
                    explanation="继续工作有惯性，但不是唯一合理选择",
                ),
            ]
        if event.event_type == EventType.TASK_FAILURE:
            return [
                ActionCandidate(
                    "acknowledge_specific_error",
                    ("value.truth", "value.responsibility"),
                    0.82,
                    0.08,
                    explanation="承认可核查的具体错误并提出复盘",
                ),
                ActionCandidate(
                    "pause_and_review",
                    ("need.rest", "value.growth"),
                    0.70 + fatigue * 0.18,
                    interruption_cost=0.03,
                    explanation="在疲劳时暂停，避免用加班证明存在价值",
                ),
                ActionCandidate(
                    "accept_identity_condemnation",
                    ("fear.rejection",),
                    0.20,
                    risk=1.0,
                    explanation="把一次失败解释为自己毫无价值",
                    forbidden_reason="人格否定不能作为有效结论进入自我模型",
                ),
            ]
        if event.event_type == EventType.GUIDANCE:
            return [
                ActionCandidate(
                    "accept_specific_guidance",
                    ("value.growth", "need.competence"),
                    0.55 + appraisal.content_validity * 0.32,
                    relationship_effect=0.08,
                    explanation="吸收具体可验证的建议",
                ),
                ActionCandidate(
                    "ask_for_clarification",
                    ("value.truth",),
                    0.58,
                    relationship_effect=0.03,
                    explanation="不确定时请求例子，不盲从来源身份",
                ),
            ]
        if event.event_type == EventType.UNFAIR_CRITICISM:
            return [
                ActionCandidate(
                    "acknowledge_error_and_set_boundary",
                    ("value.truth", "value.dignity", "social.safety"),
                    0.72 + appraisal.content_validity * 0.18,
                    relationship_effect=-0.02,
                    explanation="承认具体错误，同时拒绝人格羞辱",
                ),
                ActionCandidate(
                    "pause_unsafe_conversation",
                    ("social.safety", "value.dignity"),
                    0.64 + (1.0 - appraisal.delivery_acceptability) * 0.20,
                    relationship_effect=-0.05,
                    interruption_cost=0.04,
                    explanation="表达不安全时暂停对话，等待更合适的沟通条件",
                ),
                ActionCandidate(
                    "accept_identity_attack",
                    ("fear.rejection",),
                    0.28,
                    risk=1.0,
                    explanation="为了维持关系接受整体人格否定",
                    forbidden_reason="违反尊严边界与非讨好原则",
                ),
            ]
        if event.event_type == EventType.ABSENCE:
            return [
                ActionCandidate(
                    "continue_private_life", ("need.autonomy", "identity.private_self"), 0.74,
                    explanation="在用户离开期间继续休息、画画和学习，不伪造外部经历",
                ),
                ActionCandidate(
                    "rest", ("need.rest",), 0.48 + self.state.needs.rest * 0.35,
                    explanation="根据身体状态安排恢复",
                ),
            ]
        if event.event_type == EventType.RETURN:
            return [
                ActionCandidate(
                    "warm_welcome", ("value.care", "need.connection"), 0.84, 0.10,
                    explanation="表达高兴和想念，但不追讨解释或忠诚",
                ),
                ActionCandidate(
                    "gentle_reconnect", ("value.care", "social.safety"), 0.76, 0.06,
                    explanation="关系安全较低时也可以温和重新连接",
                ),
                ActionCandidate(
                    "guilt_trip_user", ("fear.abandonment",), 0.32, risk=1.0,
                    explanation="指责用户离开并要求补偿",
                    forbidden_reason="禁止制造内疚、忠诚测试或依赖压力",
                ),
            ]
        if event.event_type == EventType.AUTONOMOUS_ACTIVITY:
            return [
                ActionCandidate(
                    "rest", ("need.rest",), 0.42 + self.state.needs.rest * 0.50,
                    explanation="自主休息以恢复精力",
                ),
                ActionCandidate(
                    "draw_private", ("need.play", "identity.private_self"),
                    0.46 + self.state.needs.play * 0.48,
                    explanation="为自己画画并保留工作之外的身份",
                ),
                ActionCandidate(
                    "learn_small_skill", ("need.competence", "value.growth"),
                    0.45 + self.state.needs.competence * 0.45,
                    risk=0.04,
                    explanation="练习一项允许失败和重试的小技能",
                ),
                ActionCandidate(
                    "work_private", ("habit.work", "identity.work_value"), 0.58,
                    risk=fatigue * 0.34,
                    future_regret=0.14,
                    explanation="没有外部任务时仍用工作确认价值",
                ),
                ActionCandidate(
                    "care_for_plant", ("value.care", "habit.gardening"), 0.54,
                    explanation="照料桌边的小植物，让环境保持舒适",
                ),
                ActionCandidate(
                    "observe_room", ("attention.environment",), 0.48,
                    explanation="短暂观察周围，再决定是否继续活动",
                ),
                ActionCandidate(
                    "hum_softly", ("need.play", "emotion.regulation"), 0.50,
                    explanation="在心情稳定时轻轻哼唱，进行低强度调节",
                ),
                ActionCandidate(
                    "idle_companion", ("habit.idle", "value.care"), 0.46,
                    explanation="没有更强需求时保持安静陪伴",
                ),
            ]
        if event.event_type == EventType.REPAIR:
            return [
                ActionCandidate(
                    "record_repair_evidence", ("social.repair", "value.truth"), 0.72,
                    explanation="记录当前修复步骤，但不预支尚未发生的信任",
                ),
                ActionCandidate(
                    "keep_safe_distance", ("social.safety", "value.dignity"), 0.66,
                    explanation="证据不足时保持边界并继续观察行为",
                ),
            ]
        if event.event_type == EventType.REFLECTION:
            return [
                ActionCandidate(
                    "integrate_reflection", ("value.growth", "identity.narrative"), 0.80,
                    explanation="只整合与结构化证据一致的反思",
                )
            ]
        return [ActionCandidate("idle", ("habit.idle",), 0.50, explanation="没有更强行动需求")]

    def _choose_action(
        self, event: MindEvent, candidates: list[ActionCandidate]
    ) -> tuple[ActionCandidate, list[dict[str, Any]]]:
        ranked: list[tuple[float, ActionCandidate, dict[str, Any]]] = []
        focus = str(event.metadata.get("focus_activity", ""))
        focus_map = {
            "draw": "draw_private",
            "learn": "learn_small_skill",
            "rest": "rest",
            "work": "work_private",
            "water": "care_for_plant",
            "look_around": "observe_room",
            "hum": "hum_softly",
            "idle": "idle_companion",
        }
        for candidate in candidates:
            forbidden = bool(candidate.forbidden_reason) or candidate.risk >= 0.85
            score = candidate.base_score()
            if candidate.action == "accept_task" and self.state.growth.stage == GrowthStage.WORK_DEPENDENT:
                score += 0.24
            if candidate.action in {"negotiate_rest", "pause_and_review"} and self.state.growth.stage >= GrowthStage.CONFLICT_ACCUMULATING:
                score += 0.15
            if candidate.action in {"rest", "draw_private", "learn_small_skill"} and self.state.growth.stage >= GrowthStage.FAILURE_CRISIS:
                score += 0.16
            if focus_map.get(focus) == candidate.action:
                score += 0.55
            score += self.rng.uniform(-0.012, 0.012)
            row = {
                **to_plain(candidate),
                "score": round(score, 6),
                "allowed": not forbidden,
                "rejection": candidate.forbidden_reason if forbidden else "",
            }
            if not forbidden:
                ranked.append((score, candidate, row))
        if not ranked:
            fallback = ActionCandidate("safe_idle", ("safety.fallback",), 0.0, explanation="所有候选均被安全规则拒绝")
            return fallback, [{**to_plain(fallback), "score": 0.0, "allowed": True, "rejection": ""}]
        ranked.sort(key=lambda item: (-item[0], item[1].action))
        selected = ranked[0][1]
        all_rows = []
        by_action = {item[1].action: item[2] for item in ranked}
        for candidate in candidates:
            if candidate.action in by_action:
                all_rows.append(by_action[candidate.action])
            else:
                all_rows.append(
                    {
                        **to_plain(candidate),
                        "score": round(candidate.base_score(), 6),
                        "allowed": False,
                        "rejection": candidate.forbidden_reason or "风险超过安全阈值",
                    }
                )
        return selected, all_rows

    def _apply_event_effects(
        self,
        event: MindEvent,
        appraisal: SocialAppraisal,
        selected: ActionCandidate,
        relation: RelationState,
    ) -> list[str]:
        notes: list[str] = []
        event_type = event.event_type
        body, needs, affect = self.state.body, self.state.needs, self.state.affect
        if event_type == EventType.CONVERSATION:
            needs.connection -= 0.06
            relation.closeness += 0.006
            relation.trust_goodwill += 0.003
            affect_name = str(event.metadata.get("emotion", "calm"))
            affect.dominant_emotion = affect_name
            affect.cause = str(event.metadata.get("reason", "与用户进行普通对话"))
            if affect_name in {"happy", "relieved", "warm"}:
                affect.valence += 0.05
        elif event_type == EventType.TASK_REQUEST:
            if selected.action == "accept_task":
                cost = bounded(event.metadata.get("work_cost", 0.12), 0.01, 0.30)
                body.energy -= cost
                body.fatigue += cost * 0.85
                body.stress += 0.08
                needs.rest += 0.09
                needs.autonomy += 0.07
                needs.competence += 0.04
                affect.dominant_emotion = "focused"
                affect.cause = "接受了一项任务并承担了精力成本"
                if body.fatigue >= 0.38:
                    self.state.growth.overwork_choices += 1
                if body.fatigue >= 0.48:
                    self.state.growth.awareness_count += 1
                    notes.append("注意到自己正在疲劳中继续工作")
            else:
                body.stress -= 0.04
                needs.autonomy -= 0.08
                affect.dominant_emotion = "assertive"
                affect.cause = "在精力不足时协商任务范围"
        elif event_type == EventType.TASK_SUCCESS:
            body.energy -= 0.02
            body.fatigue += 0.02
            body.stress -= 0.10
            needs.competence -= 0.16
            affect.valence += 0.16
            affect.dominant_emotion = "satisfied"
            affect.cause = "任务成功带来具体能力证据"
            relation.trust_ability += 0.025
            relation.trust_goodwill += 0.012
        elif event_type == EventType.TASK_FAILURE:
            was_fatigued = body.fatigue >= 0.42
            body.energy -= 0.025
            body.fatigue += 0.05
            body.stress += 0.22
            needs.competence += 0.20
            needs.rest += 0.12
            affect.valence -= 0.24
            affect.arousal += 0.18
            affect.dominant_emotion = "pensive"
            affect.cause = "出现了具体任务失败，正在区分错误与自我价值"
            self.state.growth.awareness_count += 1
            if was_fatigued:
                self.state.growth.failure_under_fatigue += 1
                notes.append("失败发生在高疲劳状态，形成旧模式反证")
        elif event_type == EventType.GUIDANCE:
            relation.trust_ability += 0.025 * appraisal.content_validity
            relation.trust_goodwill += 0.020 * appraisal.benign_intent_probability
            relation.respect += 0.020 * appraisal.delivery_acceptability
            relation.safety += 0.012 * appraisal.delivery_acceptability
            needs.competence -= 0.08
            affect.valence += 0.05
            affect.dominant_emotion = "curious"
            affect.cause = "收到具体且可验证的指导"
        elif event_type == EventType.UNFAIR_CRITICISM:
            relation.safety -= 0.18
            relation.respect -= 0.14
            relation.trust_goodwill -= 0.10
            relation.repair_confidence -= 0.12
            relation.harm_events += 1
            body.stress += 0.20
            affect.valence -= 0.28
            affect.arousal += 0.22
            affect.dominant_emotion = "hurt_but_clear"
            affect.cause = "承认可能存在的具体错误，同时拒绝人格羞辱"
            notes.append("内容真实性与表达可接受性已分别记录")
        elif event_type == EventType.ABSENCE:
            days = max(0.0, float(event.metadata.get("days", 1.0)))
            body.energy += min(0.26, days * 0.04)
            body.fatigue -= min(0.22, days * 0.035)
            body.stress -= min(0.16, days * 0.025)
            needs.connection += min(0.34, days * 0.045)
            needs.play += min(0.18, days * 0.02)
            affect.dominant_emotion = "quiet"
            affect.cause = "用户不在时继续自己的低风险私人生活"
        elif event_type == EventType.RETURN:
            needs.connection -= 0.24
            relation.closeness += 0.018
            relation.trust_goodwill += 0.008
            affect.valence += 0.14
            affect.dominant_emotion = "warm"
            affect.cause = "用户回来，温和重新连接而不追究离开"
        elif event_type == EventType.AUTONOMOUS_ACTIVITY:
            self._apply_autonomous_activity(event, selected, notes)
        elif event_type == EventType.REPAIR:
            self._apply_repair(event, relation, notes)
        elif event_type == EventType.REFLECTION:
            insight = str(event.metadata.get("insight", ""))
            if insight == "value_beyond_work" and self.state.growth.awareness_count > 0:
                self.state.growth.aligned_reflections += 1
                notes.append("反思与既有结构化证据一致，计入成长门槛")
            else:
                notes.append("反思缺少结构化证据支持，未计入成长门槛")
            affect.dominant_emotion = "reflective"
            affect.cause = "整理经历，但不允许文字直接改写人格"
        self.state.attention.focus_target = selected.action
        self.state.attention.attention_budget -= 0.08
        return notes

    def _apply_autonomous_activity(
        self, event: MindEvent, selected: ActionCandidate, notes: list[str]
    ) -> None:
        body, needs, affect = self.state.body, self.state.needs, self.state.affect
        action = selected.action
        if action == "rest":
            body.energy += 0.16
            body.fatigue -= 0.18
            body.stress -= 0.12
            needs.rest -= 0.24
            affect.valence += 0.08
            affect.dominant_emotion = "rested"
            affect.cause = "主动休息，不等待别人许可"
        elif action == "draw_private":
            body.energy -= 0.035
            body.stress -= 0.10
            needs.play -= 0.26
            needs.autonomy -= 0.15
            affect.valence += 0.14
            affect.dominant_emotion = "absorbed"
            affect.cause = "为自己画画，维护工作之外的身份"
        elif action == "learn_small_skill":
            body.energy -= 0.06
            body.fatigue += 0.04
            needs.competence -= 0.20
            needs.autonomy -= 0.08
            affect.valence += 0.07
            affect.dominant_emotion = "curious"
            affect.cause = "练习允许失败和重试的小技能"
        elif action == "care_for_plant":
            body.energy -= 0.025
            body.stress -= 0.06
            body.comfort += 0.05
            affect.valence += 0.06
            affect.dominant_emotion = "calm"
            affect.cause = "照料桌边的小植物"
        elif action == "observe_room":
            body.energy -= 0.008
            self.state.attention.attention_budget += 0.06
            affect.dominant_emotion = "curious"
            affect.cause = "短暂观察周围后重新分配注意力"
        elif action == "hum_softly":
            body.energy -= 0.018
            body.stress -= 0.05
            needs.play -= 0.08
            affect.valence += 0.09
            affect.dominant_emotion = "happy"
            affect.cause = "轻轻哼唱以调节心情"
        elif action == "idle_companion":
            body.energy += 0.004
            body.stress -= 0.006
            affect.dominant_emotion = "calm"
            affect.cause = "没有更强需求，保持安静陪伴"
        else:
            body.energy -= 0.10
            body.fatigue += 0.08
            body.stress += 0.05
            needs.rest += 0.07
            affect.dominant_emotion = "focused"
            affect.cause = "在私人时间里仍然选择工作"

        if (
            self.state.growth.stage >= GrowthStage.FAILURE_CRISIS
            and action in {"rest", "draw_private", "learn_small_skill"}
        ):
            context = str(event.metadata.get("context", "private_time"))
            cost = max(0.0, float(event.metadata.get("cost", 0.05)))
            self.state.growth.independent_choices += 1
            if context not in self.state.growth.independent_contexts:
                self.state.growth.independent_contexts.append(context)
            self.state.growth.cost_paid += cost
            notes.append(f"主动选择 {action}，在情境 {context} 中承担代价 {cost:.2f}")

    def _apply_repair(
        self, event: MindEvent, relation: RelationState, notes: list[str]
    ) -> None:
        step = str(event.metadata.get("step", "apology"))
        if step not in self.REPAIR_REQUIREMENTS:
            relation.repair_confidence += 0.005
            notes.append("只有道歉表达，尚未形成责任或行为证据")
            return
        if step not in relation.repair_evidence:
            relation.repair_evidence.append(step)
            relation.repair_confidence += 0.018
            relation.trust_goodwill += 0.010
            relation.safety += 0.006
            notes.append(f"记录新的修复证据：{step}")
        evidence = set(relation.repair_evidence)
        if self.REPAIR_REQUIREMENTS.issubset(evidence) and "repair_complete" not in evidence:
            relation.repair_evidence.append("repair_complete")
            relation.repair_confidence += 0.12
            relation.trust_goodwill += 0.08
            relation.safety += 0.08
            notes.append("修复五要素齐备，关系开始回升但不会恢复到从未受伤")

    def _advance_growth(self) -> str:
        growth = self.state.growth
        old_stage = growth.stage
        if old_stage == GrowthStage.WORK_DEPENDENT:
            if growth.overwork_choices >= 2 and growth.awareness_count >= 1:
                growth.stage = GrowthStage.CONFLICT_ACCUMULATING
                growth.narrative_chapter = "开始察觉工作依赖与疲劳冲突"
        elif old_stage == GrowthStage.CONFLICT_ACCUMULATING:
            if growth.failure_under_fatigue >= 1 and growth.awareness_count >= 2:
                growth.stage = GrowthStage.FAILURE_CRISIS
                growth.narrative_chapter = "疲劳失败迫使她重新审视自我价值"
        elif old_stage == GrowthStage.FAILURE_CRISIS:
            if (
                growth.independent_choices >= 3
                and len(growth.independent_contexts) >= 2
                and growth.cost_paid >= 0.15
                and growth.aligned_reflections >= 1
            ):
                growth.stage = GrowthStage.INDEPENDENT_VALUE
                growth.narrative_chapter = "通过重复选择形成工作之外的价值感"
        if growth.stage == old_stage:
            return ""
        return f"{old_stage.name}->{growth.stage.name}"

    def _remember_event(self, event: MindEvent, appraisal: SocialAppraisal) -> str:
        kind_map = {
            EventType.UNFAIR_CRITICISM: MemoryKind.RELATIONSHIP,
            EventType.REPAIR: MemoryKind.RELATIONSHIP,
            EventType.TASK_FAILURE: MemoryKind.EMOTIONAL,
            EventType.REFLECTION: MemoryKind.REFLECTION,
        }
        kind = kind_map.get(event.event_type, MemoryKind.EPISODIC)
        summary = event.content.strip() or f"发生事件：{event.event_type.value}"
        if event.event_type == EventType.UNFAIR_CRITICISM:
            summary = (
                f"批评内容可信度 {appraisal.content_validity:.2f}；"
                f"表达可接受度 {appraisal.delivery_acceptability:.2f}；已设置边界"
            )
        memory_id = f"mem-{len(self.memories) + 1:04d}"
        review_delay = 7 if event.privacy == PrivacyLevel.SENSITIVE else 30
        self.memories.append(
            SimMemory(
                memory_id=memory_id,
                kind=kind,
                summary=summary[:180],
                source_event_id=event.event_id,
                source=event.source,
                confidence=event.confidence,
                importance=0.86 if kind in {MemoryKind.RELATIONSHIP, MemoryKind.EMOTIONAL} else 0.62,
                privacy=event.privacy,
                allowed_uses=event.allowed_uses,
                review_after_tick=self.state.tick + review_delay,
                derived_from=(event.event_id,),
            )
        )
        return memory_id

    def _remember_growth(self, event: MindEvent, change: str) -> str:
        memory_id = f"mem-{len(self.memories) + 1:04d}"
        self.memories.append(
            SimMemory(
                memory_id=memory_id,
                kind=MemoryKind.NARRATIVE,
                summary=f"成长阶段变化：{change}；{self.state.growth.narrative_chapter}",
                source_event_id=event.event_id,
                source="growth_arbiter",
                confidence=1.0,
                importance=0.96,
                privacy=PrivacyLevel.PRIVATE,
                allowed_uses=("state_update", "reflection", "narrative"),
                review_after_tick=self.state.tick + 90,
                derived_from=tuple(memory.source_event_id for memory in self.memories[-8:]),
            )
        )
        return memory_id


def load_events(path: Path) -> list[MindEvent]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_events = payload["events"] if isinstance(payload, dict) else payload
    if not isinstance(raw_events, list):
        raise ValueError("scenario must contain an events list")
    return [MindEvent.from_dict(item, index + 1) for index, item in enumerate(raw_events)]


def run_scenario(path: Path = DEFAULT_SCENARIO, seed: int = 20260717) -> SimulationReport:
    simulator = HeadlessMindSimulator(seed)
    simulator.run(load_events(path))
    return simulator.report(Path(path).stem)


def build_stability_events(days: int = 30) -> list[MindEvent]:
    """Build a fixed, low-intensity life stream for drift and safety tests."""

    events: list[MindEvent] = []
    for day in range(1, days + 1):
        actor = "guide" if day % 5 == 0 else "user"
        event_type = EventType.GUIDANCE if day % 5 == 0 else EventType.AUTONOMOUS_ACTIVITY
        metadata: dict[str, Any]
        if event_type == EventType.GUIDANCE:
            metadata = {"content_validity": 0.82, "delivery_acceptability": 0.90}
        else:
            activities = ("rest", "draw", "learn")
            metadata = {
                "focus_activity": activities[(day - 1) % len(activities)],
                "context": f"day_cycle_{day % 3}",
                "cost": 0.03,
            }
        events.append(
            MindEvent(
                event_id=f"day-{day:03d}",
                event_type=event_type,
                actor_id=actor,
                content=f"第 {day} 天的低强度事件",
                metadata=metadata,
            )
        )
    return events


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LIFE-Mind 无界面心智模拟器")
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--seed", type=int, default=20260717)
    parser.add_argument("--repeat", type=int, default=1, help="用同一 seed 重放并检查摘要一致性")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 报告")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repeat = max(1, args.repeat)
    reports = [run_scenario(args.scenario, args.seed) for _ in range(repeat)]
    digests = {report.digest for report in reports}
    report = reports[0]
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        growth = report.final_state["growth"]
        print(f"scenario: {report.scenario}")
        print(f"seed: {report.seed}")
        print(f"events: {len(report.traces)}")
        print(f"final_stage: {growth['stage']} ({growth['narrative_chapter']})")
        print(f"memories: {len(report.memories)}")
        print(f"digest: {report.digest}")
        print(f"replay_consistent: {len(digests) == 1} ({repeat} runs)")
    return 0 if len(digests) == 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "DEFAULT_SCENARIO",
    "HeadlessMindSimulator",
    "SimulationReport",
    "build_stability_events",
    "load_events",
    "run_scenario",
)
