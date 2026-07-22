from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import uuid
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
        self.assertIn("--checkpoint", result.stdout)
        self.assertIn("--db-path", result.stdout)
        self.assertIn("--pet-stderr", result.stdout)

    def test_stable_samples_pass_all_thresholds(self) -> None:
        samples = [
            ResourceSample(0.0, 120 * MIB, 125 * MIB, 80, 1.0),
            ResourceSample(3600.0, 126 * MIB, 145 * MIB, 86, 4.0),
        ]
        report = summarize_samples(samples)
        self.assertTrue(report["passed"])
        self.assertEqual(report["rss_growth_bytes"], 6 * MIB)
        self.assertEqual(report["handle_growth"], 6)

    def test_memory_or_handle_growth_fails_the_gate(self) -> None:
        samples = [
            ResourceSample(0.0, 100 * MIB, 100 * MIB, 40, 0.0),
            ResourceSample(60.0, 420 * MIB, 600 * MIB, 150, 2.0),
        ]
        report = summarize_samples(samples, SoakThresholds())
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["lifetime_peak_rss_within_hard_limit"])
        self.assertFalse(report["checks"]["steady_max_rss_within_limit"])
        self.assertFalse(report["checks"]["steady_p95_rss_within_limit"])
        self.assertTrue(report["checks"]["rss_growth_within_limit"])
        self.assertFalse(report["checks"]["handle_growth_within_limit"])

    def test_startup_high_water_mark_is_not_the_normal_operating_gate(self) -> None:
        samples = [
            ResourceSample(float(index * 60), rss * MIB, 440 * MIB, 280, float(index))
            for index, rss in enumerate([390, 330, 280, 250, 230, 220, 218, 220, 219, 221])
        ]

        report = summarize_samples(samples)

        self.assertTrue(report["passed"])
        self.assertTrue(report["warmup_applied"])
        self.assertEqual(report["steady_max_rss_bytes"], 221 * MIB)
        self.assertEqual(report["peak_rss_bytes"], 440 * MIB)

    def test_sustained_high_working_set_fails_even_below_hard_peak(self) -> None:
        samples = [
            ResourceSample(float(index * 60), 340 * MIB, 410 * MIB, 280, float(index))
            for index in range(10)
        ]

        report = summarize_samples(samples)

        self.assertFalse(report["passed"])
        self.assertTrue(report["checks"]["lifetime_peak_rss_within_hard_limit"])
        self.assertFalse(report["checks"]["steady_p95_rss_within_limit"])

    def test_long_term_growth_rate_catches_a_slow_leak(self) -> None:
        samples = [
            ResourceSample(
                float(300 + index * 900),
                (120 + index * 5) * MIB,
                220 * MIB,
                280 + index,
                float(index * 20),
            )
            for index in range(9)
        ]

        report = summarize_samples(samples)

        self.assertTrue(report["trend_checks_applied"])
        self.assertLess(report["rss_growth_bytes"], 64 * MIB)
        self.assertFalse(report["checks"]["rss_growth_rate_within_limit"])
        self.assertFalse(report["passed"])

    def test_sustained_single_core_cpu_usage_fails_the_gate(self) -> None:
        samples = [
            ResourceSample(0.0, 180 * MIB, 220 * MIB, 280, 0.0),
            ResourceSample(600.0, 182 * MIB, 220 * MIB, 281, 300.0),
        ]

        report = summarize_samples(samples)

        self.assertEqual(report["single_core_cpu_percent"], 50.0)
        self.assertFalse(report["checks"]["single_core_cpu_within_hard_limit"])
        self.assertFalse(report["passed"])

    def test_cpu_budget_is_normalized_across_logical_processors(self) -> None:
        samples = [
            ResourceSample(0.0, 180 * MIB, 220 * MIB, 280, 0.0),
            ResourceSample(600.0, 182 * MIB, 220 * MIB, 281, 60.0),
        ]

        report = summarize_samples(samples, logical_cpu_count=4)

        self.assertEqual(report["single_core_cpu_percent"], 10.0)
        self.assertEqual(report["normalized_cpu_percent"], 2.5)
        self.assertTrue(report["checks"]["single_core_cpu_within_hard_limit"])
        self.assertFalse(report["checks"]["average_cpu_within_limit"])
        self.assertFalse(report["passed"])

    def test_v1_report_can_be_reassessed_without_overwriting_it(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        raw_samples = [
            {
                "elapsed_seconds": float(index * 60),
                "rss_bytes": rss * MIB,
                "peak_rss_bytes": 440 * MIB,
                "handle_count": 280,
                "cpu_seconds": float(index),
            }
            for index, rss in enumerate([390, 330, 280, 250, 230, 220, 218, 220, 219, 221])
        ]
        test_temp_root = project_root / "tmp"
        test_temp_root.mkdir(parents=True, exist_ok=True)
        source = test_temp_root / f"old-report-{uuid.uuid4().hex}.json"
        reassessed = source.with_name(f"{source.stem}-reassessed.json")
        try:
            source.write_text(
                json.dumps({"passed": False, "samples": raw_samples}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "tools/reassess_soak_report.py",
                    str(source),
                ],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(source.is_file())
            payload = json.loads(reassessed.read_text(encoding="utf-8"))
            self.assertEqual(payload["policy_version"], 2)
            self.assertTrue(payload["passed"])
            self.assertFalse(payload["reassessment"]["source_passed"])
        finally:
            source.unlink(missing_ok=True)
            reassessed.unlink(missing_ok=True)

    def test_out_of_order_samples_are_rejected(self) -> None:
        samples = [
            ResourceSample(60.0, 180 * MIB, 220 * MIB, 280, 2.0),
            ResourceSample(30.0, 180 * MIB, 220 * MIB, 280, 3.0),
        ]

        with self.assertRaises(ValueError):
            summarize_samples(samples)

    def test_partial_checkpoint_cannot_pass_a_full_duration_gate(self) -> None:
        samples = [
            ResourceSample(0.0, 180 * MIB, 220 * MIB, 280, 0.0),
            ResourceSample(600.0, 182 * MIB, 220 * MIB, 281, 10.0),
        ]

        report = summarize_samples(
            samples,
            expected_duration_seconds=8 * 3600.0,
        )

        self.assertFalse(report["checks"]["duration_reached"])
        self.assertFalse(report["passed"])

    def test_short_startup_smoke_does_not_apply_long_term_growth_gate(self) -> None:
        samples = [
            ResourceSample(0.0, 136 * MIB, 180 * MIB, 425, 0.0),
            ResourceSample(30.0, 211 * MIB, 236 * MIB, 421, 2.1),
        ]

        report = summarize_samples(
            samples,
            expected_duration_seconds=30.0,
        )

        self.assertFalse(report["growth_checks_applied"])
        self.assertTrue(report["checks"]["rss_growth_within_limit"])
        self.assertTrue(report["passed"])

    def test_periodic_animation_memory_levels_do_not_look_like_a_leak(self) -> None:
        rss_levels = [120, 120, 190, 265, 190, 190, 120, 120, 190, 265, 120, 190]
        samples = [
            ResourceSample(float(index), rss * MIB, 290 * MIB, 80, index * 0.02)
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
            ResourceSample(
                float(300 + index * 60),
                rss * MIB,
                220 * MIB,
                80,
                index * 0.05,
            )
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
