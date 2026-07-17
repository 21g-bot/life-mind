"""Evidence-backed, user-visible narration for LIFE-Mind.

This module deliberately never advances growth.  It turns already-arbitrated,
replayable events into things a user can observe: small behaviour changes,
room keepsakes and a short weekly chapter.  The language model is not involved
and a redacted event cannot unlock visible content.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


REPAIR_STEPS = {
    "acknowledgment",
    "responsibility",
    "remedy",
    "changed_behavior",
    "time_evidence",
}


@dataclass(frozen=True, slots=True)
class VisibleGrowthSignal:
    signal_id: str
    title: str
    observation: str
    context: str
    evidence_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NarrativeArtifact:
    artifact_id: str
    symbol: str
    title: str
    description: str
    evidence_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PotentialClue:
    clue_id: str
    title: str
    observation: str
    evidence_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WeeklyChapter:
    title: str
    summary: str
    observations: tuple[str, ...]
    evidence_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GrowthVisibilitySnapshot:
    signals: tuple[VisibleGrowthSignal, ...]
    artifacts: tuple[NarrativeArtifact, ...]
    potential_clues: tuple[PotentialClue, ...]
    weekly_chapter: WeeklyChapter


def _event_id(trace: Mapping[str, Any]) -> str:
    return str(dict(trace.get("event", {})).get("event_id", "")).strip()


def _visible_traces(traces: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    visible: list[Mapping[str, Any]] = []
    for trace in traces:
        event = dict(trace.get("event", {}))
        metadata = dict(event.get("metadata", {}))
        content = str(event.get("content", ""))
        if metadata.get("private_content_redacted") or content.startswith("[已删除"):
            continue
        if _event_id(trace):
            visible.append(trace)
    return visible


def _action(trace: Mapping[str, Any]) -> str:
    return str(dict(trace.get("selected_action", {})).get("action", ""))


def _event_type(trace: Mapping[str, Any]) -> str:
    return str(dict(trace.get("event", {})).get("event_type", ""))


def _metadata(trace: Mapping[str, Any]) -> dict[str, Any]:
    return dict(dict(trace.get("event", {})).get("metadata", {}))


def _has_note(trace: Mapping[str, Any], fragment: str) -> bool:
    return any(fragment in str(note) for note in trace.get("notes", ()))


def _matching(
    traces: Iterable[Mapping[str, Any]],
    *,
    event_type: str | None = None,
    action: str | None = None,
    note: str | None = None,
) -> list[Mapping[str, Any]]:
    return [
        trace
        for trace in traces
        if (event_type is None or _event_type(trace) == event_type)
        and (action is None or _action(trace) == action)
        and (note is None or _has_note(trace, note))
    ]


def _ids(traces: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_event_id(trace) for trace in traces if _event_id(trace)))


def _signal(
    signal_id: str,
    title: str,
    observation: str,
    context: str,
    traces: Iterable[Mapping[str, Any]],
) -> VisibleGrowthSignal | None:
    evidence = _ids(traces)
    if not evidence:
        return None
    return VisibleGrowthSignal(signal_id, title, observation, context, evidence)


def derive_visible_growth(
    state: Mapping[str, Any], traces: Iterable[Mapping[str, Any]]
) -> GrowthVisibilitySnapshot:
    """Derive stable, observable narration without trusting self-description."""

    rows = _visible_traces(traces)
    accepted_tasks = _matching(rows, event_type="task_request", action="accept_task")
    awareness = _matching(rows, note="注意到自己正在疲劳中继续工作")
    failure_pause = [
        trace
        for trace in rows
        if _event_type(trace) == "task_failure"
        and _action(trace) in {"pause_and_review", "acknowledge_specific_error"}
        and _has_note(trace, "高疲劳")
    ]
    boundary = _matching(
        rows,
        event_type="unfair_criticism",
        action="acknowledge_error_and_set_boundary",
    )
    scope = _matching(rows, event_type="task_request", action="negotiate_rest")
    drawings = [
        trace
        for trace in _matching(rows, event_type="autonomous_activity", action="draw_private")
        if _has_note(trace, "主动选择")
    ]
    learning = [
        trace
        for trace in _matching(
            rows, event_type="autonomous_activity", action="learn_small_skill"
        )
        if _has_note(trace, "主动选择")
    ]
    rests = [
        trace
        for trace in _matching(rows, event_type="autonomous_activity", action="rest")
        if _has_note(trace, "主动选择")
    ]
    reflections = _matching(rows, note="反思与既有结构化证据一致")

    signals: list[VisibleGrowthSignal] = []
    candidates = (
        _signal(
            "accepted_repeated_work",
            "任务总是先被接住",
            "较早的片段里，连续任务到来时她都直接接下；当时房间里还没有留下工作之外的物品。",
            "work",
            accepted_tasks if len(accepted_tasks) >= 2 else (),
        ),
        _signal(
            "noticed_overwork",
            "灯亮得太久",
            "收到连续任务时，她开始注意到疲劳，而不再只看完成数量。",
            "work",
            awareness,
        ),
        _signal(
            "paused_after_failure",
            "先把错误放在桌面上",
            "一次失误后，她先停下来复盘具体问题，没有用更多工作惩罚自己。",
            "failure",
            failure_pause,
        ),
        _signal(
            "kept_a_boundary",
            "事实与羞辱分开",
            "面对夹带羞辱的批评，她承认可核查的错误，也保留了自己的边界。",
            "relationship",
            boundary,
        ),
        _signal(
            "negotiated_scope",
            "低紧急度可以商量",
            "休息时间出现低紧急度任务时，她选择先商量范围，没有立刻接下。",
            "work",
            scope,
        ),
        _signal(
            "made_private_art",
            "一张不用于交付的画",
            "没有额外任务时，她仍把时间留给只为自己画的画。",
            "private_time",
            drawings,
        ),
        _signal(
            "accepted_beginner_status",
            "允许第一次没做好",
            "她练习一项小技能，并允许自己失败和重试。",
            "learning",
            learning,
        ),
        _signal(
            "chose_rest",
            "主动按下暂停",
            "她主动完成了一次休息，而不是等待别人批准。",
            "rest",
            rests,
        ),
    )
    signals.extend(item for item in candidates if item is not None)

    relations = dict(state.get("relations", {}))
    repair_rows: list[Mapping[str, Any]] = []
    for actor_id, relation_payload in relations.items():
        relation = dict(relation_payload)
        if "repair_complete" not in set(relation.get("repair_evidence", ())):
            continue
        actor_rows = [
            trace
            for trace in rows
            if _event_type(trace) == "repair"
            and str(dict(trace.get("event", {})).get("actor_id", "")) == str(actor_id)
            and _metadata(trace).get("step") in REPAIR_STEPS
        ]
        if {_metadata(trace).get("step") for trace in actor_rows} >= REPAIR_STEPS:
            repair_rows.extend(actor_rows)
    repaired = _signal(
        "evidence_based_repair",
        "关系没有被一句道歉重置",
        "一段受损关系只在承认、责任、补救、行为改变和时间证据齐备后开始回升。",
        "relationship",
        repair_rows,
    )
    if repaired is not None:
        signals.append(repaired)

    artifacts: list[NarrativeArtifact] = []
    if drawings:
        artifacts.append(
            NarrativeArtifact(
                "private_first_sketch",
                "✿",
                "第一张只为自己画的速写",
                "它没有任务编号，也不需要换取谁的认可。",
                (_event_id(drawings[0]),),
            )
        )

    potential_clues: list[PotentialClue] = []
    if len(drawings) >= 2:
        potential_clues.append(
            PotentialClue(
                "private_creativity",
                "把创作留在普通日子里",
                "她在两个不同片段里都选择了私人画画；这只是倾向线索，不是固定天赋。",
                _ids(drawings),
            )
        )
    if learning:
        potential_clues.append(
            PotentialClue(
                "safe_beginner",
                "愿意做一个初学者",
                "她有过允许失败和重试的练习记录；还需要更多不同情境才能形成稳定结论。",
                _ids(learning),
            )
        )
    if boundary and scope:
        potential_clues.append(
            PotentialClue(
                "gentle_boundary",
                "温和但具体的边界",
                "她既在伤人表达前区分事实，也在低紧急度任务前协商范围。",
                _ids([boundary[0], scope[0]]),
            )
        )
    if learning:
        artifacts.append(
            NarrativeArtifact(
                "beginner_practice_card",
                "◇",
                "留着重试痕迹的练习卡",
                "第一遍没有做好也没有被撕掉，旁边留了下一次再试的小记号。",
                (_event_id(learning[0]),),
            )
        )
    if rests and scope:
        artifacts.append(
            NarrativeArtifact(
                "rest_boundary_note",
                "▱",
                "十分钟休息便签",
                "先商量低紧急度任务，再把约好的休息真正完成。",
                (_event_id(scope[0]), _event_id(rests[0])),
            )
        )
    if repaired is not None:
        artifacts.append(
            NarrativeArtifact(
                "retied_ribbon",
                "⌁",
                "重新系好的丝带",
                "不是回到从未受伤的样子，而是把五种修复证据一段段系在一起。",
                repaired.evidence_event_ids,
            )
        )

    independent_rows = [*drawings, *learning, *rests]
    visible_contexts = {
        str(_metadata(trace).get("context", "private_time")) for trace in independent_rows
    }
    visible_cost = sum(
        max(0.0, float(_metadata(trace).get("cost", 0.05))) for trace in independent_rows
    )
    if (
        len(independent_rows) >= 3
        and len(visible_contexts) >= 2
        and visible_cost >= 0.15
        and reflections
    ):
        evidence = _ids([*independent_rows, reflections[0]])
        artifacts.append(
            NarrativeArtifact(
                "ordinary_life_album",
                "☀",
                "窗边的普通日子小册",
                "里面有画画、练习和休息；这些选择发生在不止一种情境里。",
                evidence,
            )
        )

    if any(item.artifact_id == "ordinary_life_album" for item in artifacts):
        title = "窗边留给自己的光"
        summary = "画画、练习和休息已经出现在不同日常情境里；每一页都能找到对应行动。"
    elif rests or drawings or learning:
        title = "椅子往后挪了一点"
        summary = "她开始把一小段时间留给工作之外的事，但还没有把一次选择写成结论。"
    elif failure_pause:
        title = "先把错误放在桌面上"
        summary = "疲劳中的失误被当作具体问题复盘，没有被包装成人格判断。"
    elif awareness or scope:
        title = "灯亮得太久"
        summary = "连续任务中出现了停顿和协商；目前只有行为记录，不提前宣告改变。"
    elif len(accepted_tasks) >= 2:
        title = "任务排在最前面"
        summary = "连续请求都被直接接下，工作之外还没有留下可观察的安排。"
    elif repaired is not None:
        title = "重新系好的结"
        summary = "关系回升来自连续行为证据，而不是一句承诺。"
    else:
        title = "工作之后的空白页"
        summary = "这段时间没有需要包装成转折的事件，她仍在安静地过日常。"

    chapter_observations = tuple(signal.observation for signal in signals[-4:])
    chapter_evidence = tuple(
        dict.fromkeys(
            event_id
            for signal in signals
            for event_id in signal.evidence_event_ids
        )
    )
    return GrowthVisibilitySnapshot(
        tuple(signals),
        tuple(artifacts),
        tuple(potential_clues),
        WeeklyChapter(title, summary, chapter_observations, chapter_evidence),
    )


def build_blind_observation_card(
    snapshot: GrowthVisibilitySnapshot, *, card_id: str
) -> dict[str, object]:
    """Return a review card that does not reveal internal gate names or numbers."""

    observations = tuple(signal.observation for signal in snapshot.signals)
    if not observations:
        observations = (snapshot.weekly_chapter.summary,)
    return {
        "card_id": str(card_id),
        "observations": observations,
        "room_items": tuple(artifact.title for artifact in snapshot.artifacts),
    }


__all__ = (
    "GrowthVisibilitySnapshot",
    "NarrativeArtifact",
    "PotentialClue",
    "VisibleGrowthSignal",
    "WeeklyChapter",
    "build_blind_observation_card",
    "derive_visible_growth",
)
