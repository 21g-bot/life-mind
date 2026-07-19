from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from life_mind.data_benchmark import (
    DataBenchmarkThresholds,
    MIB,
    run_data_reliability_benchmark,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DataReliabilityBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = PROJECT_ROOT / "tmp" / f"benchmark-test-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_small_gate_proves_replay_backup_and_recovery(self) -> None:
        report = run_data_reliability_benchmark(
            self.root,
            event_count=120,
            thresholds=DataBenchmarkThresholds(
                max_create_seconds=15.0,
                max_startup_seconds=15.0,
                max_backup_seconds=15.0,
                max_recovery_seconds=15.0,
                max_database_bytes=32 * MIB,
                max_rss_bytes=512 * MIB,
            ),
        )

        self.assertTrue(report["passed"], report)
        self.assertEqual(report["event_count"], 120)
        self.assertEqual(report["recovery_status"], "restored")
        self.assertTrue(all(report["checks"].values()))
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("长期数据验收事件", serialized)

    def test_event_count_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            run_data_reliability_benchmark(self.root, event_count=0)


if __name__ == "__main__":
    unittest.main()
