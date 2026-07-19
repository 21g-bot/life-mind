"""Process resource sampling and pass/fail summaries for desktop soak tests."""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


MIB = 1024 * 1024
SOAK_POLICY_VERSION = 2


@dataclass(frozen=True, slots=True)
class ResourceSample:
    elapsed_seconds: float
    rss_bytes: int
    peak_rss_bytes: int
    handle_count: int
    cpu_seconds: float


@dataclass(frozen=True, slots=True)
class SoakThresholds:
    # PeakWorkingSetSize is a process-lifetime high-water mark on Windows. It
    # includes startup and image-decoder allocations before monitoring begins,
    # so it is a catastrophic ceiling rather than the normal operating budget.
    max_peak_rss_bytes: int = 512 * MIB
    max_steady_rss_bytes: int = 384 * MIB
    max_steady_p95_rss_bytes: int = 320 * MIB
    max_rss_growth_bytes: int = 64 * MIB
    max_rss_growth_per_hour_bytes: int = 8 * MIB
    max_handle_growth: int = 64
    max_handle_growth_per_hour: float = 8.0
    max_single_core_cpu_percent: float = 35.0
    warmup_seconds: float = 300.0
    trend_min_duration_seconds: float = 3600.0
    min_steady_samples: int = 5
    min_duration_completion_ratio: float = 0.995


def _nearest_rank(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(len(ordered) * percentile))
    return ordered[min(len(ordered) - 1, rank - 1)]


def _low_quartile(values: list[int]) -> int:
    return _nearest_rank(values, 0.25)


def _median(values: list[int]) -> int:
    return _nearest_rank(values, 0.50)


if os.name == "nt":
    from ctypes import wintypes

    class _FileTime(ctypes.Structure):
        _fields_ = (("low", wintypes.DWORD), ("high", wintypes.DWORD))

    class _ProcessMemoryCounters(ctypes.Structure):
        _fields_ = (
            ("cb", wintypes.DWORD),
            ("page_fault_count", wintypes.DWORD),
            ("peak_working_set_size", ctypes.c_size_t),
            ("working_set_size", ctypes.c_size_t),
            ("quota_peak_paged_pool_usage", ctypes.c_size_t),
            ("quota_paged_pool_usage", ctypes.c_size_t),
            ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
            ("quota_non_paged_pool_usage", ctypes.c_size_t),
            ("pagefile_usage", ctypes.c_size_t),
            ("peak_pagefile_usage", ctypes.c_size_t),
        )


def _filetime_seconds(value) -> float:
    ticks = (int(value.high) << 32) | int(value.low)
    return ticks / 10_000_000.0


def sample_process(pid: int, *, elapsed_seconds: float = 0.0) -> ResourceSample:
    """Read one process without requiring psutil."""

    if os.name != "nt":
        raise RuntimeError("当前稳定性采样器只支持 Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    process_query_limited_information = 0x1000
    process_vm_read = 0x0010
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(
        process_query_limited_information | process_vm_read,
        False,
        int(pid),
    )
    if not handle:
        raise ProcessLookupError(f"无法读取进程 {pid}")
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise OSError(ctypes.get_last_error(), "GetExitCodeProcess 失败")
        if int(exit_code.value) != 259:  # STILL_ACTIVE
            raise ProcessLookupError(f"进程 {pid} 已经退出")
        memory = _ProcessMemoryCounters()
        memory.cb = ctypes.sizeof(memory)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo 失败")
        handle_count = wintypes.DWORD()
        if not kernel32.GetProcessHandleCount(handle, ctypes.byref(handle_count)):
            raise OSError(ctypes.get_last_error(), "GetProcessHandleCount 失败")
        creation, exit_time, kernel, user = _FileTime(), _FileTime(), _FileTime(), _FileTime()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise OSError(ctypes.get_last_error(), "GetProcessTimes 失败")
        return ResourceSample(
            elapsed_seconds=round(float(elapsed_seconds), 3),
            rss_bytes=int(memory.working_set_size),
            peak_rss_bytes=int(memory.peak_working_set_size),
            handle_count=int(handle_count.value),
            cpu_seconds=round(_filetime_seconds(kernel) + _filetime_seconds(user), 4),
        )
    finally:
        kernel32.CloseHandle(handle)


@contextmanager
def prevent_system_sleep():
    """Keep Windows awake for a monitor run without changing its power plan."""

    if os.name != "nt":
        yield False
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_thread_execution_state = kernel32.SetThreadExecutionState
    set_thread_execution_state.argtypes = (wintypes.DWORD,)
    set_thread_execution_state.restype = wintypes.DWORD
    es_continuous = 0x80000000
    es_system_required = 0x00000001
    if not set_thread_execution_state(es_continuous | es_system_required):
        raise OSError(ctypes.get_last_error(), "无法阻止系统在稳定性测试期间睡眠")
    try:
        yield True
    finally:
        set_thread_execution_state(es_continuous)


def summarize_samples(
    samples: list[ResourceSample],
    thresholds: SoakThresholds = SoakThresholds(),
    *,
    expected_duration_seconds: float | None = None,
) -> dict[str, object]:
    if not samples:
        raise ValueError("稳定性报告至少需要一个采样点")
    if any(
        current.elapsed_seconds < previous.elapsed_seconds
        for previous, current in zip(samples, samples[1:])
    ):
        raise ValueError("稳定性采样点必须按 elapsed_seconds 递增")
    if any(
        item.rss_bytes < 0
        or item.peak_rss_bytes < 0
        or item.handle_count < 0
        or item.cpu_seconds < 0
        for item in samples
    ):
        raise ValueError("稳定性采样资源值不能为负数")
    first, last = samples[0], samples[-1]
    lifetime_peak = max(item.peak_rss_bytes for item in samples)
    steady_samples = [
        item for item in samples if item.elapsed_seconds >= thresholds.warmup_seconds
    ]
    warmup_applied = len(steady_samples) >= max(1, thresholds.min_steady_samples)
    if not warmup_applied:
        steady_samples = samples

    steady_rss_values = [item.rss_bytes for item in steady_samples]
    steady_max_rss = max(steady_rss_values)
    steady_p95_rss = _nearest_rank(steady_rss_values, 0.95)
    steady_first, steady_last = steady_samples[0], steady_samples[-1]
    if len(steady_samples) < 6:
        growth_window_size = 1
        baseline_rss = steady_first.rss_bytes
        final_baseline_rss = steady_last.rss_bytes
        baseline_handles = steady_first.handle_count
        final_baseline_handles = steady_last.handle_count
    else:
        # Desktop animations deliberately move between several resident-memory
        # levels as clips are decoded. Compare low-quartile baselines from the
        # first and last windows so the result measures floor drift instead of
        # whichever animation happened to be visible at either endpoint. Peak
        # RSS remains a separate hard gate for transient allocations.
        growth_window_size = max(3, math.ceil(len(steady_samples) * 0.2))
        first_window = steady_samples[:growth_window_size]
        final_window = steady_samples[-growth_window_size:]
        baseline_rss = _low_quartile([item.rss_bytes for item in first_window])
        final_baseline_rss = _low_quartile([item.rss_bytes for item in final_window])
        baseline_handles = _median([item.handle_count for item in first_window])
        final_baseline_handles = _median([item.handle_count for item in final_window])
    rss_growth = final_baseline_rss - baseline_rss
    handle_growth = final_baseline_handles - baseline_handles
    steady_duration_seconds = max(
        0.0,
        steady_last.elapsed_seconds - steady_first.elapsed_seconds,
    )
    trend_applied = steady_duration_seconds >= thresholds.trend_min_duration_seconds
    trend_hours = steady_duration_seconds / 3600.0 if steady_duration_seconds else 0.0
    rss_growth_per_hour = rss_growth / trend_hours if trend_hours else 0.0
    handle_growth_per_hour = handle_growth / trend_hours if trend_hours else 0.0
    observed_duration = max(0.0, last.elapsed_seconds - first.elapsed_seconds)
    expected_duration = (
        max(0.0, float(expected_duration_seconds))
        if expected_duration_seconds is not None
        else None
    )
    duration_completion_ratio = (
        min(1.0, observed_duration / expected_duration)
        if expected_duration and expected_duration > 0.0
        else None
    )
    cpu_seconds = max(0.0, last.cpu_seconds - first.cpu_seconds)
    single_core_cpu_percent = (
        cpu_seconds / observed_duration * 100.0 if observed_duration else 0.0
    )
    growth_checks_applied = (
        warmup_applied or observed_duration >= thresholds.warmup_seconds
    )
    checks = {
        "duration_reached": (
            duration_completion_ratio is None
            or duration_completion_ratio >= thresholds.min_duration_completion_ratio
        ),
        "lifetime_peak_rss_within_hard_limit": (
            lifetime_peak <= thresholds.max_peak_rss_bytes
        ),
        "steady_max_rss_within_limit": (
            steady_max_rss <= thresholds.max_steady_rss_bytes
        ),
        "steady_p95_rss_within_limit": (
            steady_p95_rss <= thresholds.max_steady_p95_rss_bytes
        ),
        "rss_growth_within_limit": (
            not growth_checks_applied
            or rss_growth <= thresholds.max_rss_growth_bytes
        ),
        "rss_growth_rate_within_limit": (
            not trend_applied
            or rss_growth_per_hour <= thresholds.max_rss_growth_per_hour_bytes
        ),
        "handle_growth_within_limit": handle_growth <= thresholds.max_handle_growth,
        "handle_growth_rate_within_limit": (
            not trend_applied
            or handle_growth_per_hour <= thresholds.max_handle_growth_per_hour
        ),
        "average_cpu_within_limit": (
            single_core_cpu_percent <= thresholds.max_single_core_cpu_percent
        ),
    }
    return {
        "policy_version": SOAK_POLICY_VERSION,
        "passed": all(checks.values()),
        "duration_seconds": last.elapsed_seconds,
        "expected_duration_seconds": expected_duration,
        "duration_completion_ratio": duration_completion_ratio,
        "sample_count": len(samples),
        "initial_rss_bytes": first.rss_bytes,
        "final_rss_bytes": last.rss_bytes,
        "endpoint_rss_delta_bytes": last.rss_bytes - first.rss_bytes,
        "growth_baseline_rss_bytes": baseline_rss,
        "growth_final_rss_bytes": final_baseline_rss,
        "growth_window_sample_count": growth_window_size,
        "warmup_applied": warmup_applied,
        "warmup_seconds": thresholds.warmup_seconds if warmup_applied else 0.0,
        "steady_sample_count": len(steady_samples),
        "steady_duration_seconds": steady_duration_seconds,
        "steady_max_rss_bytes": steady_max_rss,
        "steady_p95_rss_bytes": steady_p95_rss,
        "peak_rss_bytes": lifetime_peak,
        "rss_growth_bytes": rss_growth,
        "rss_growth_per_hour_bytes": rss_growth_per_hour,
        "initial_handle_count": first.handle_count,
        "final_handle_count": last.handle_count,
        "growth_baseline_handle_count": baseline_handles,
        "growth_final_handle_count": final_baseline_handles,
        "handle_growth": handle_growth,
        "handle_growth_per_hour": handle_growth_per_hour,
        "growth_checks_applied": growth_checks_applied,
        "trend_checks_applied": trend_applied,
        "cpu_seconds": cpu_seconds,
        "single_core_cpu_percent": single_core_cpu_percent,
        "thresholds": asdict(thresholds),
        "checks": checks,
        "samples": [asdict(item) for item in samples],
    }


def monitor_process(
    pid: int,
    *,
    duration_seconds: float,
    sample_seconds: float = 60.0,
    thresholds: SoakThresholds = SoakThresholds(),
    on_sample: Callable[[ResourceSample, int], None] | None = None,
) -> dict[str, object]:
    with prevent_system_sleep() as sleep_prevention_active:
        started = time.monotonic()
        samples: list[ResourceSample] = []
        while True:
            elapsed = time.monotonic() - started
            samples.append(sample_process(pid, elapsed_seconds=elapsed))
            if on_sample is not None:
                on_sample(samples[-1], len(samples))
            if elapsed >= duration_seconds:
                break
            time.sleep(min(sample_seconds, max(0.05, duration_seconds - elapsed)))
        report = summarize_samples(
            samples,
            thresholds,
            expected_duration_seconds=duration_seconds,
        )
        report["sleep_prevention_active"] = sleep_prevention_active
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="监控 LIFE-Mind 桌宠进程的内存、句柄和 CPU")
    parser.add_argument("--pid", type=int, required=True, help="待监控桌宠进程 PID")
    parser.add_argument("--hours", type=float, default=8.0, help="监控时长，默认 8 小时")
    parser.add_argument("--sample-seconds", type=float, default=60.0, help="采样间隔")
    parser.add_argument("--output", type=Path, required=True, help="JSON 报告路径")
    args = parser.parse_args(argv)
    report = monitor_process(
        args.pid,
        duration_seconds=max(0.1, args.hours * 3600.0),
        sample_seconds=max(0.1, args.sample_seconds),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "samples"}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "MIB",
    "ResourceSample",
    "SOAK_POLICY_VERSION",
    "SoakThresholds",
    "monitor_process",
    "prevent_system_sleep",
    "sample_process",
    "summarize_samples",
)
