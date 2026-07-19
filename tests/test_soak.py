from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from life_mind.soak import (
    MIB,
    ResourceSample,
    SoakThresholds,
    monitor_process,
    sample_process,
    summarize_samples,
)


class SoakMonitorTests(unittest.TestCase):
    def test_soak_cli_can_import_project_when_run_as_a_script(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-B", "tools/run_desktop_soak.py", "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--hours", result.stdout)

    def test_stable_samples_pass_all_thresholds(self) -> None:
        samples = [
            ResourceSample(0.0, 120 * MIB, 125 * MIB, 80, 1.0),
            ResourceSample(3600.0, 132 * MIB, 145 * MIB, 86, 4.0),
        ]
        report = summarize_samples(samples)
        self.assertTrue(report["passed"])
        self.assertEqual(report["rss_growth_bytes"], 12 * MIB)
        self.assertEqual(report["handle_growth"], 6)

    def test_memory_or_handle_growth_fails_the_gate(self) -> None:
        samples = [
            ResourceSample(0.0, 100 * MIB, 100 * MIB, 40, 0.0),
            ResourceSample(60.0, 190 * MIB, 400 * MIB, 150, 2.0),
        ]
        report = summarize_samples(samples, SoakThresholds())
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["peak_rss_within_limit"])
        self.assertFalse(report["checks"]["rss_growth_within_limit"])
        self.assertFalse(report["checks"]["handle_growth_within_limit"])

    def test_periodic_animation_memory_levels_do_not_look_like_a_leak(self) -> None:
        rss_levels = [120, 120, 190, 265, 190, 190, 120, 120, 190, 265, 120, 190]
        samples = [
            ResourceSample(float(index), rss * MIB, 290 * MIB, 80, float(index))
            for index, rss in enumerate(rss_levels)
        ]

        report = summarize_samples(samples)

        self.assertTrue(report["passed"])
        self.assertEqual(report["growth_baseline_rss_bytes"], 120 * MIB)
        self.assertEqual(report["growth_final_rss_bytes"], 120 * MIB)
        self.assertEqual(report["rss_growth_bytes"], 0)
        self.assertEqual(report["endpoint_rss_delta_bytes"], 70 * MIB)

    def test_steady_state_floor_growth_still_fails_the_gate(self) -> None:
        rss_levels = [100, 100, 180, 180, 195, 195, 195, 195, 195, 195]
        samples = [
            ResourceSample(float(index), rss * MIB, 220 * MIB, 80, float(index))
            for index, rss in enumerate(rss_levels)
        ]

        report = summarize_samples(samples)

        self.assertFalse(report["passed"])
        self.assertEqual(report["rss_growth_bytes"], 95 * MIB)
        self.assertFalse(report["checks"]["rss_growth_within_limit"])

    @unittest.skipUnless(os.name == "nt", "Windows process counters")
    def test_current_process_can_be_sampled_without_psutil(self) -> None:
        sample = sample_process(os.getpid())
        self.assertGreater(sample.rss_bytes, 0)
        self.assertGreater(sample.peak_rss_bytes, 0)
        self.assertGreater(sample.handle_count, 0)

    @unittest.skipUnless(os.name == "nt", "Windows process counters")
    def test_exited_process_is_not_reported_as_zero_resource_sample(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            cwd=Path(__file__).resolve().parents[1],
        )
        process.wait(timeout=10)

        with self.assertRaises(ProcessLookupError):
            sample_process(process.pid)

    @unittest.skipUnless(os.name == "nt", "Windows process counters")
    def test_monitor_reports_progress_after_every_sample(self) -> None:
        progress: list[tuple[int, float]] = []

        report = monitor_process(
            os.getpid(),
            duration_seconds=0.12,
            sample_seconds=0.05,
            on_sample=lambda sample, count: progress.append((count, sample.elapsed_seconds)),
        )

        self.assertEqual(len(progress), report["sample_count"])
        self.assertEqual([item[0] for item in progress], list(range(1, len(progress) + 1)))
        self.assertTrue(report["sleep_prevention_active"])


if __name__ == "__main__":
    unittest.main()
