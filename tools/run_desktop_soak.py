"""Launch an isolated desktop pet and monitor it for the Stage 1 soak gate."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = PROJECT_ROOT / ".deps" / "python"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if DEPENDENCIES.is_dir() and str(DEPENDENCIES) not in sys.path:
    sys.path.insert(0, str(DEPENDENCIES))

from life_mind.soak import monitor_process


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动并监控隔离的 LIFE-Mind 桌宠")
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--sample-seconds", type=float, default=60.0)
    parser.add_argument("--startup-seconds", type=float, default=12.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "tmp" / "desktop-soak-report.json",
    )
    parser.add_argument(
        "--status",
        type=Path,
        default=PROJECT_ROOT / "tmp" / "desktop-soak-status.json",
        help="每次采样后原子更新的进度文件",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        help="逐次保存原始采样；默认在最终报告旁写入 .partial.json",
    )
    parser.add_argument("--pet-stdout", type=Path, help="桌宠子进程标准输出日志")
    parser.add_argument("--pet-stderr", type=Path, help="桌宠子进程错误日志")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=PROJECT_ROOT / "tmp" / "desktop-soak.db",
        help="隔离测试数据库路径",
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        default=PROJECT_ROOT / "tmp" / "desktop-soak-config.json",
        help="隔离测试配置路径",
    )
    parser.add_argument("--windowed", action="store_true", help="显示调试标题栏")
    args = parser.parse_args(argv)
    checkpoint = args.checkpoint or args.output.with_suffix(args.output.suffix + ".partial.json")
    pet_stdout_path = args.pet_stdout or args.output.with_suffix(".pet.stdout.log")
    pet_stderr_path = args.pet_stderr or args.output.with_suffix(".pet.stderr.log")

    command = [
        sys.executable,
        "-B",
        str(PROJECT_ROOT / "run_pet.py"),
        "--db-path",
        str(args.db_path),
        "--config-path",
        str(args.config_path),
    ]
    if args.windowed:
        command.append("--windowed")
    environment = os.environ.copy()
    environment["LIFE_MIND_NAME"] = "耐久测试桌宠（临时数据）"
    pet_stdout_path.parent.mkdir(parents=True, exist_ok=True)
    pet_stderr_path.parent.mkdir(parents=True, exist_ok=True)
    pet_stdout = pet_stdout_path.open("w", encoding="utf-8")
    pet_stderr = pet_stderr_path.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=pet_stdout,
            stderr=pet_stderr,
        )
    except BaseException:
        pet_stdout.close()
        pet_stderr.close()
        raise
    started_at = utc_now()
    write_json_atomic(
        args.status,
        {
            "status": "starting",
            "started_at": started_at,
            "updated_at": started_at,
            "pet_pid": process.pid,
            "target_hours": args.hours,
            "sample_seconds": args.sample_seconds,
            "test_instance": True,
            "output": str(args.output),
            "checkpoint": str(checkpoint),
            "pet_stdout": str(pet_stdout_path),
            "pet_stderr": str(pet_stderr_path),
            "db_path": str(args.db_path),
            "config_path": str(args.config_path),
        },
    )
    progress_samples: list[dict[str, object]] = []
    try:
        time.sleep(max(1.0, args.startup_seconds))
        if process.poll() is not None:
            raise RuntimeError(f"桌宠在稳定性采样前退出，退出码 {process.returncode}")

        def record_progress(sample, sample_count: int) -> None:
            progress_samples.append(asdict(sample))
            write_json_atomic(
                checkpoint,
                {
                    "schema": "life-mind-soak-checkpoint-v1",
                    "status": "running",
                    "started_at": started_at,
                    "updated_at": utc_now(),
                    "pet_pid": process.pid,
                    "target_hours": args.hours,
                    "sample_seconds": args.sample_seconds,
                    "sample_count": sample_count,
                    "samples": progress_samples,
                },
            )
            write_json_atomic(
                args.status,
                {
                    "status": "running",
                    "started_at": started_at,
                    "updated_at": utc_now(),
                    "pet_pid": process.pid,
                    "target_hours": args.hours,
                    "sample_seconds": args.sample_seconds,
                    "test_instance": True,
                    "sample_count": sample_count,
                    "elapsed_seconds": sample.elapsed_seconds,
                    "latest_sample": asdict(sample),
                    "output": str(args.output),
                    "checkpoint": str(checkpoint),
                    "pet_stdout": str(pet_stdout_path),
                    "pet_stderr": str(pet_stderr_path),
                    "db_path": str(args.db_path),
                    "config_path": str(args.config_path),
                },
            )

        report = monitor_process(
            process.pid,
            duration_seconds=max(0.1, args.hours * 3600.0),
            sample_seconds=max(0.1, args.sample_seconds),
            on_sample=record_progress,
        )
        write_json_atomic(args.output, report)
        checkpoint.unlink(missing_ok=True)
        write_json_atomic(
            args.status,
            {
                "status": "passed" if report["passed"] else "failed_gate",
                "started_at": started_at,
                "updated_at": utc_now(),
                "pet_pid": process.pid,
                "target_hours": args.hours,
                "sample_seconds": args.sample_seconds,
                "test_instance": True,
                "sample_count": report["sample_count"],
                "elapsed_seconds": report["duration_seconds"],
                "passed": report["passed"],
                "checks": report["checks"],
                "output": str(args.output),
                "checkpoint": str(checkpoint),
                "pet_exit_code": process.poll(),
                "pet_exit_reason": "monitor_completed",
                "pet_stdout": str(pet_stdout_path),
                "pet_stderr": str(pet_stderr_path),
                "db_path": str(args.db_path),
                "config_path": str(args.config_path),
            },
        )
        print(json.dumps({key: value for key, value in report.items() if key != "samples"}, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 2
    except BaseException as error:
        write_json_atomic(
            args.status,
            {
                "status": "interrupted" if isinstance(error, KeyboardInterrupt) else "error",
                "started_at": started_at,
                "updated_at": utc_now(),
                "pet_pid": process.pid,
                "target_hours": args.hours,
                "error": str(error) or type(error).__name__,
                "output": str(args.output),
                "checkpoint": str(checkpoint),
                "pet_exit_code": process.poll(),
                "pet_exit_reason": (
                    "exited_before_monitor_completed"
                    if process.poll() is not None
                    else "monitor_error"
                ),
                "pet_stdout": str(pet_stdout_path),
                "pet_stderr": str(pet_stderr_path),
                "db_path": str(args.db_path),
                "config_path": str(args.config_path),
            },
        )
        raise
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=4)
        pet_stdout.close()
        pet_stderr.close()


if __name__ == "__main__":
    raise SystemExit(main())
