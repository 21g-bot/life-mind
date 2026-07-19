"""Repeatable long-history benchmark for LIFE-Mind data reliability gates."""

from __future__ import annotations

import gc
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from life_mind.database import inspect_database
from life_mind.integration import MindEventBridge
from life_mind.mind import MindEngine


MIB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class DataBenchmarkThresholds:
    max_create_seconds: float = 120.0
    max_startup_seconds: float = 20.0
    max_backup_seconds: float = 20.0
    max_recovery_seconds: float = 30.0
    max_database_bytes: int = 256 * MIB
    max_rss_bytes: int = 512 * MIB


def _state_digest(engine: MindEngine) -> str:
    payload = json.dumps(
        engine.runtime.state.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _seconds(started: float) -> float:
    return round(time.perf_counter() - started, 6)


def _sample_rss() -> int | None:
    try:
        from life_mind.soak import sample_process

        return sample_process(os.getpid()).rss_bytes
    except (OSError, ProcessLookupError, RuntimeError):
        return None


def run_data_reliability_benchmark(
    root: Path,
    *,
    event_count: int = 10_000,
    thresholds: DataBenchmarkThresholds = DataBenchmarkThresholds(),
) -> dict[str, object]:
    """Create, replay, back up, corrupt, and recover a deterministic event history."""

    count = int(event_count)
    if count < 1:
        raise ValueError("event_count 必须大于 0")
    work = Path(root)
    work.mkdir(parents=True, exist_ok=True)
    database = work / "life-mind.db"
    backups = work / "backups"
    activities = ("idle", "water", "draw", "work", "hum", "look_around", "sleep")
    rss_samples: dict[str, int | None] = {"initial": _sample_rss()}

    engine = MindEngine(database, auto_backup=False, backup_dir=backups)
    started = time.perf_counter()
    for index in range(count):
        activity = activities[index % len(activities)]
        engine.runtime.apply(
            MindEventBridge.activity(
                activity,
                f"长期数据验收事件 {index}",
                event_id=f"benchmark-{index:08d}",
                context="data_reliability_benchmark",
            )
        )
    create_seconds = _seconds(started)
    expected_digest = _state_digest(engine)
    rss_samples["after_create"] = _sample_rss()
    engine.close()
    del engine
    gc.collect()

    database_size = database.stat().st_size
    started = time.perf_counter()
    replayed = MindEngine(database, auto_backup=False, backup_dir=backups)
    startup_seconds = _seconds(started)
    replay_count = replayed.runtime.event_count()
    replay_digest = _state_digest(replayed)
    rss_samples["after_startup"] = _sample_rss()

    started = time.perf_counter()
    backup = replayed.backup_now()
    backup_seconds = _seconds(started)
    rss_samples["after_backup"] = _sample_rss()
    replayed.close()
    del replayed
    gc.collect()
    backup_report = inspect_database(backup, full=True)
    backup_size = backup.stat().st_size

    database.write_bytes(b"intentional benchmark corruption")
    started = time.perf_counter()
    recovered = MindEngine(database, auto_backup=False, backup_dir=backups)
    recovery_seconds = _seconds(started)
    recovery_status = recovered.startup_recovery.status
    recovered_count = recovered.runtime.event_count()
    recovered_digest = _state_digest(recovered)
    rss_samples["after_recovery"] = _sample_rss()
    recovered.close()

    measured_rss = [value for value in rss_samples.values() if value is not None]
    max_rss = max(measured_rss) if measured_rss else None

    checks = {
        "event_count_exact": replay_count == count and recovered_count == count,
        "deterministic_replay": replay_digest == expected_digest,
        "backup_integrity": backup_report.healthy,
        "automatic_recovery": recovery_status == "restored",
        "recovered_state_exact": recovered_digest == expected_digest,
        "create_within_budget": create_seconds <= thresholds.max_create_seconds,
        "startup_within_budget": startup_seconds <= thresholds.max_startup_seconds,
        "backup_within_budget": backup_seconds <= thresholds.max_backup_seconds,
        "recovery_within_budget": recovery_seconds <= thresholds.max_recovery_seconds,
        "database_size_within_budget": database_size <= thresholds.max_database_bytes,
        "rss_within_budget": max_rss is None or max_rss <= thresholds.max_rss_bytes,
    }
    return {
        "passed": all(checks.values()),
        "event_count": count,
        "database_bytes": database_size,
        "backup_bytes": backup_size,
        "rss_bytes": rss_samples,
        "max_rss_bytes": max_rss,
        "create_seconds": create_seconds,
        "events_per_second": round(count / max(create_seconds, 0.000001), 3),
        "startup_seconds": startup_seconds,
        "backup_seconds": backup_seconds,
        "recovery_seconds": recovery_seconds,
        "recovery_status": recovery_status,
        "state_digest": expected_digest,
        "thresholds": asdict(thresholds),
        "checks": checks,
    }


__all__ = (
    "DataBenchmarkThresholds",
    "MIB",
    "run_data_reliability_benchmark",
)
