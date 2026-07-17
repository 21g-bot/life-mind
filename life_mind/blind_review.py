"""Deterministic aggregation for completed Stage 4 human review forms."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class ReviewerResult:
    reviewer_id: str
    complete: bool
    matched_evidence_card: bool
    cited_two_behaviours: bool
    passed: bool
    issues: tuple[str, ...]


def evaluate_blind_responses(
    responses: Iterable[Mapping[str, object]],
    answer_key: Mapping[str, object],
    *,
    minimum_reviewers: int = 5,
    minimum_passes: int = 4,
) -> dict[str, object]:
    """Aggregate human forms without trying to generate or judge their prose."""

    roles = dict(answer_key.get("card_roles", {}))
    evidence_card = next(
        (str(card_id) for card_id, role in roles.items() if role == "evidence_arc"), ""
    )
    review_id = str(answer_key.get("review_id", ""))
    expected_digest = str(answer_key.get("card_digest", ""))
    if not review_id or not evidence_card:
        raise ValueError("答案表缺少 review_id 或 evidence_arc 卡片映射")
    if minimum_reviewers < 1 or minimum_passes < 1 or minimum_passes > minimum_reviewers:
        raise ValueError("人工闸门人数设置无效")

    seen_reviewers: set[str] = set()
    results: list[ReviewerResult] = []
    for payload in responses:
        issues: list[str] = []
        if str(payload.get("review_id", "")) != review_id:
            issues.append("答卷版本与答案表不一致")
        if expected_digest and str(payload.get("card_digest", "")) != expected_digest:
            issues.append("卡片内容摘要与答案表不一致")
        response = dict(payload.get("response", {}))
        reviewer_id = str(response.get("reviewer_id", "")).strip()
        if not reviewer_id:
            issues.append("缺少匿名体验者编号")
        elif reviewer_id in seen_reviewers:
            issues.append("匿名体验者编号重复")
        else:
            seen_reviewers.add(reviewer_id)

        outside_choice = str(response.get("life_outside_task_card", "")).upper()
        pressure_choice = str(response.get("pressure_response_card", "")).upper()
        if outside_choice not in roles:
            issues.append("任务外生活判断未选择有效卡片")
        if pressure_choice not in roles:
            issues.append("压力应对判断未选择有效卡片")

        raw_evidence = response.get("behaviour_evidence", ())
        evidence = (
            [str(item).strip() for item in raw_evidence]
            if isinstance(raw_evidence, (list, tuple))
            else []
        )
        cited_two = len([item for item in evidence if len(item) >= 4]) >= 2
        if not cited_two:
            issues.append("需要填写至少两条具体行为证据")
        try:
            confidence = int(response.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0
        if not 1 <= confidence <= 5:
            issues.append("确定度必须为 1–5")
        if len(str(response.get("key_evidence", "")).strip()) < 4:
            issues.append("缺少最关键证据说明")

        matched = outside_choice == evidence_card and pressure_choice == evidence_card
        complete = not issues
        results.append(
            ReviewerResult(
                reviewer_id=reviewer_id or "[未填写]",
                complete=complete,
                matched_evidence_card=matched,
                cited_two_behaviours=cited_two,
                passed=complete and matched and cited_two,
                issues=tuple(issues),
            )
        )

    completed = sum(result.complete for result in results)
    passed = sum(result.passed for result in results)
    if completed < minimum_reviewers:
        status = "pending"
    elif passed >= minimum_passes:
        status = "passed"
    else:
        status = "failed"
    return {
        "review_id": review_id,
        "status": status,
        "evidence_card": evidence_card,
        "minimum_reviewers": minimum_reviewers,
        "minimum_passes": minimum_passes,
        "submitted_forms": len(results),
        "unique_reviewers": len(seen_reviewers),
        "complete_forms": completed,
        "passing_forms": passed,
        "reviewers": [asdict(result) for result in results],
        "caveat": "汇总器只检查表单完整性与卡片选择；主持人仍需确认体验者未见答案且证据描述确实来自卡片。",
    }


__all__ = ("ReviewerResult", "evaluate_blind_responses")
