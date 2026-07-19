"""Test-only worker that is intentionally killed with an open WAL transaction."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from life_mind.integration import MindEventBridge
from life_mind.mind import MindEngine


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args()

    engine = MindEngine(args.db, auto_backup=False)
    engine.runtime.apply(
        MindEventBridge.activity(
            "idle",
            "强制终止测试中的已提交事件",
            event_id="crash-probe-committed",
            context="crash_probe",
        )
    )
    engine.connection.execute("BEGIN IMMEDIATE")
    engine.connection.execute(
        """INSERT INTO mind_events_v2(event_id, event_json, trace_json, created_at)
        VALUES ('crash-probe-uncommitted', '{}', '{}', '2026-07-19T00:00:00+00:00')"""
    )
    args.ready.write_text(str(os.getpid()), encoding="ascii")
    while True:
        time.sleep(1.0)


if __name__ == "__main__":
    raise SystemExit(main())
