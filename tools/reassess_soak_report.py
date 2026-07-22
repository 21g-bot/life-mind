"""Re-evaluate a completed or partial soak report with the current policy."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from life_mind.soak import ResourceSample, SOAK_POLICY_VERSION, summarize_samples


def load_samples(path: Path) -> tuple[dict[str, object], list[ResourceSample]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_samples = payload.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise ValueError("报告或检查点中没有可重评的 samples")
    samples: list[ResourceSample] = []
    for index, item in enumerate(raw_samples, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个采样点格式无效")
        try:
            samples.append(
                ResourceSample(
                    elapsed_seconds=float(item["elapsed_seconds"]),
                    rss_bytes=int(item["rss_bytes"]),
                    peak_rss_bytes=int(item["peak_rss_bytes"]),
                    handle_count=int(item["handle_count"]),
                    cpu_seconds=float(item["cpu_seconds"]),
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"第 {index} 个采样点字段无效") from error
    return payload, samples


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="使用当前稳定性策略重评 LIFE-Mind 耐久测试报告或检查点"
    )
    parser.add_argument("source", type=Path, help="旧报告或 .partial.json 检查点")
    parser.add_argument("--output", type=Path, help="重评报告路径")
    args = parser.parse_args(argv)

    source = args.source.resolve()
    payload, samples = load_samples(source)
    expected_duration: float | None = None
    if isinstance(payload.get("expected_duration_seconds"), (int, float)):
        expected_duration = float(payload["expected_duration_seconds"])
    elif isinstance(payload.get("target_hours"), (int, float)):
        expected_duration = float(payload["target_hours"]) * 3600.0
    report = summarize_samples(
        samples,
        expected_duration_seconds=expected_duration,
        logical_cpu_count=(
            int(payload["logical_cpu_count"])
            if isinstance(payload.get("logical_cpu_count"), int)
            else None
        ),
    )
    report["reassessment"] = {
        "policy_version": SOAK_POLICY_VERSION,
        "source_name": source.name,
        "source_policy_version": payload.get("policy_version"),
        "source_status": payload.get("status"),
        "source_passed": payload.get("passed"),
    }
    output = args.output or source.with_name(f"{source.stem}-reassessed.json")
    write_json_atomic(output, report)
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "samples"},
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"重评报告：{output}")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
