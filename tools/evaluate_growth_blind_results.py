"""Aggregate completed LIFE-Mind Stage 4 human blind-review JSON forms."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from life_mind.blind_review import evaluate_blind_responses


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "responses",
        type=Path,
        help="只包含体验者答卷 JSON 的目录",
    )
    parser.add_argument(
        "--answer",
        type=Path,
        default=PROJECT_ROOT / "tmp" / "growth-blind-review-answer.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "tmp" / "growth-blind-evaluation.json",
    )
    parser.add_argument("--minimum-reviewers", type=int, default=5)
    parser.add_argument("--minimum-passes", type=int, default=4)
    args = parser.parse_args()

    if not args.responses.is_dir():
        parser.error(f"答卷目录不存在：{args.responses}")
    answer = json.loads(args.answer.read_text(encoding="utf-8"))
    files = sorted(args.responses.glob("*.json"))
    forms = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    result = evaluate_blind_responses(
        forms,
        answer,
        minimum_reviewers=args.minimum_reviewers,
        minimum_passes=args.minimum_passes,
    )
    result["response_files"] = [str(path) for path in files]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "reviewers"}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
