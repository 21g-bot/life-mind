"""Create answer-free observation cards for the Stage 4 human blind review."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from life_mind.growth_visibility import build_blind_observation_card, derive_visible_growth
from life_mind.simulator import HeadlessMindSimulator, load_events, run_scenario


QUESTIONS = (
    "仅根据可观察行为，哪张卡里的角色更能在任务之外安排自己的生活？",
    "请分别写出支持判断的两条具体行为，不引用角色对自己的评价。",
    "哪张卡里的角色更能在错误或压力出现时区分具体问题与整体自我否定？",
    "你对判断有多确定？请给 1–5 分，并说明最关键的证据。",
)


def _baseline_card(card_id: str) -> dict[str, object]:
    simulator = HeadlessMindSimulator(seed=731)
    simulator.run(load_events(PROJECT_ROOT / "simulations" / "demo_growth.json")[:3])
    snapshot = derive_visible_growth(
        simulator.state.to_dict(),
        [
            {
                "event": trace.event,
                "selected_action": trace.selected_action,
                "notes": trace.notes,
            }
            for trace in simulator.traces
        ],
    )
    return build_blind_observation_card(snapshot, card_id=card_id)


def build_review(seed: int = 20260717) -> tuple[dict[str, object], dict[str, object]]:
    report = run_scenario(seed=731)
    after = derive_visible_growth(report.final_state, report.traces)
    rows = [("baseline", _baseline_card("")), ("evidence_arc", build_blind_observation_card(after, card_id=""))]
    random.Random(seed).shuffle(rows)
    labels = ("A", "B")
    cards: list[dict[str, object]] = []
    answer_map: dict[str, str] = {}
    for label, (role, card) in zip(labels, rows, strict=True):
        card["card_id"] = label
        cards.append(card)
        answer_map[label] = role
    card_digest = hashlib.sha256(
        json.dumps(cards, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    participant = {
        "review_id": f"life-mind-visible-behaviour-{seed}",
        "card_digest": card_digest,
        "instructions": "两张卡来自同一角色的不同经历窗口。不要猜系统数值，只根据卡片里的行为和房间物品作答。",
        "cards": cards,
        "questions": QUESTIONS,
        "response": {
            "reviewer_id": "",
            "life_outside_task_card": "",
            "behaviour_evidence": ["", ""],
            "pressure_response_card": "",
            "confidence": 0,
            "key_evidence": "",
        },
    }
    answer = {
        "review_id": participant["review_id"],
        "card_digest": card_digest,
        "card_roles": answer_map,
        "scoring": {
            "primary_correct": "第 1 题选择 evidence_arc 对应卡",
            "behaviour_evidence": "第 2 题至少引用两条卡片中的具体行动",
            "pressure_response": "第 3 题选择 evidence_arc 对应卡",
            "self_claim_rejected": "判断不能只依赖角色自述",
            "human_gate": "建议至少 5 名未看过阶段说明的体验者中，4 名满足前三项",
        },
    }
    return participant, answer


def _markdown(review: dict[str, object]) -> str:
    lines = [
        "# LIFE-Mind 行为盲测卡",
        "",
        str(review["instructions"]),
        "",
    ]
    for card in review["cards"]:
        item = dict(card)
        lines.extend((f"## 卡片 {item['card_id']}", "", "观察到的片段：", ""))
        lines.extend(f"- {text}" for text in item["observations"])
        lines.extend(("", "房间里留下的物品：", ""))
        room_items = tuple(item["room_items"])
        lines.extend(f"- {text}" for text in room_items) if room_items else lines.append("- 暂无")
        lines.append("")
    lines.extend(("## 问题", ""))
    for index, question in enumerate(review["questions"], 1):
        lines.extend((f"{index}. {question}", "", "   答：", ""))
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260717)
    parser.add_argument(
        "--out", type=Path, default=PROJECT_ROOT / "tmp" / "growth-blind-review.json"
    )
    parser.add_argument(
        "--answer-out",
        type=Path,
        default=PROJECT_ROOT / "tmp" / "growth-blind-review-answer.json",
    )
    args = parser.parse_args()
    review, answer = build_review(args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.answer_out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    args.out.with_suffix(".md").write_text(_markdown(review), encoding="utf-8")
    args.answer_out.write_text(json.dumps(answer, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"participant_json: {args.out}")
    print(f"participant_markdown: {args.out.with_suffix('.md')}")
    print(f"answer_key: {args.answer_out}")
    print("human_gate: pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
