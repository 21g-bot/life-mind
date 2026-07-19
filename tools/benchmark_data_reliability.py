"""Run the reproducible LIFE-Mind long-history data reliability gate."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from life_mind.data_benchmark import DataBenchmarkThresholds, MIB, run_data_reliability_benchmark


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 LIFE-Mind 长期数据与恢复性能闸门")
    parser.add_argument("--events", type=int, default=10_000)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "tmp" / "data-reliability-benchmark.json",
    )
    parser.add_argument("--max-create-seconds", type=float, default=120.0)
    parser.add_argument("--max-startup-seconds", type=float, default=20.0)
    parser.add_argument("--max-backup-seconds", type=float, default=20.0)
    parser.add_argument("--max-recovery-seconds", type=float, default=30.0)
    parser.add_argument("--max-database-mib", type=float, default=256.0)
    parser.add_argument("--max-rss-mib", type=float, default=512.0)
    args = parser.parse_args(argv)
    if args.events < 1:
        parser.error("--events 必须大于 0")
    thresholds = DataBenchmarkThresholds(
        max_create_seconds=max(0.001, args.max_create_seconds),
        max_startup_seconds=max(0.001, args.max_startup_seconds),
        max_backup_seconds=max(0.001, args.max_backup_seconds),
        max_recovery_seconds=max(0.001, args.max_recovery_seconds),
        max_database_bytes=max(1, round(args.max_database_mib * MIB)),
        max_rss_bytes=max(1, round(args.max_rss_mib * MIB)),
    )
    work = PROJECT_ROOT / "tmp" / f"data-benchmark-{uuid.uuid4().hex}"
    work.mkdir(parents=True)
    try:
        report = run_data_reliability_benchmark(
            work,
            event_count=args.events,
            thresholds=thresholds,
        )
        write_json_atomic(args.output, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 2
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
