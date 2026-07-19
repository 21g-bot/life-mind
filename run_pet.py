"""Launch or validate the LIFE-Mind pixel desktop pet."""

from __future__ import annotations

import argparse
import json
import platform
import re
import sqlite3
import sys
from pathlib import Path

LOCAL_DEPENDENCIES = Path(__file__).resolve().parent / ".deps" / "python"


def dependency_path_is_compatible(path: Path) -> bool:
    """Reject vendored native extensions built for another Python ABI."""

    if not path.is_dir():
        return False
    expected = f"cp{sys.version_info.major}{sys.version_info.minor}"
    tagged_extensions: set[str] = set()
    for extension in path.rglob("*.pyd"):
        match = re.search(r"\.(cp\d+)-", extension.name)
        if match:
            tagged_extensions.add(match.group(1))
    return not tagged_extensions or tagged_extensions == {expected}


if dependency_path_is_compatible(LOCAL_DEPENDENCIES) and str(LOCAL_DEPENDENCIES) not in sys.path:
    sys.path.insert(0, str(LOCAL_DEPENDENCIES))

from life_mind.apps.desktop_pet import (
    CONFIG_PATH,
    DEMO_ANIMATION_DIR,
    DEFAULT_ANIMATION_DIR,
    animation_report,
    run_desktop_pet,
)
from life_mind.demo_character import ensure_demo_character
from life_mind.database import (
    DatabaseReliabilityError,
    create_atomic_backup,
    inspect_database,
    restore_latest_backup,
    valid_backups,
)
from life_mind.mind import DEFAULT_DB_PATH
from life_mind import __version__


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LIFE-Mind 多动作像素桌宠")
    parser.add_argument(
        "--asset",
        type=Path,
        default=DEFAULT_ANIMATION_DIR,
        help="精细像素动作库目录（必须包含当前角色 manifest.json）",
    )
    parser.add_argument("--check", action="store_true", help="只检查素材，不打开窗口")
    parser.add_argument(
        "--release-check",
        action="store_true",
        help="检查冻结版素材、系统托盘和凭据库依赖，不打开窗口",
    )
    parser.add_argument("--reset-config", action="store_true", help="清除窗口位置与大小设置")
    parser.add_argument("--config-path", type=Path, default=CONFIG_PATH, help="窗口设置文件路径")
    parser.add_argument("--db-path", type=Path, help="心智数据库路径；留空使用用户本地数据库")
    maintenance = parser.add_mutually_exclusive_group()
    maintenance.add_argument(
        "--doctor",
        action="store_true",
        help="输出不含对话、路径、密钥和记忆正文的数据健康报告",
    )
    maintenance.add_argument(
        "--backup-now",
        action="store_true",
        help="立即创建经过 SQLite 完整性检查的原子备份",
    )
    maintenance.add_argument(
        "--restore-latest-backup",
        action="store_true",
        help="隔离当前数据库并恢复最近一个有效备份",
    )
    parser.add_argument("--windowed", action="store_true", help="显示普通标题栏，供界面调试使用")
    parser.add_argument(
        "--developer-mode",
        action="store_true",
        help="显式开放内部状态与心智调试器；普通启动保持黑箱",
    )
    parser.add_argument(
        "--ui-qa-lightweight",
        action="store_true",
        help="界面验收时仅加载正式像素库的待机和眨眼动作",
    )
    args = parser.parse_args(argv)
    selected_operations = sum(
        bool(value)
        for value in (
            args.check,
            args.release_check,
            args.reset_config,
            args.doctor,
            args.backup_now,
            args.restore_latest_backup,
        )
    )
    if selected_operations > 1:
        parser.error("检查、配置重置、诊断、备份和恢复操作不能同时执行")
    return args


def _print_json(payload: dict[str, object]) -> None:
    output = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
    if sys.stdout is not None:
        print(output)
        return
    # PyInstaller uses a windowed executable, so maintenance commands have no
    # console stream. Keep them observable instead of silently succeeding.
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    try:
        title = str(payload.get("application") or payload.get("operation") or "LIFE-Mind")
        dialog_output = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        if payload.get("ok") is False:
            messagebox.showerror(title, dialog_output, parent=root)
        else:
            messagebox.showinfo(title, dialog_output, parent=root)
    finally:
        root.destroy()


def _doctor_payload(database_path: Path, asset_path: Path) -> tuple[dict[str, object], bool]:
    report = inspect_database(database_path, full=True)
    backups = valid_backups(database_path)
    animation: dict[str, object]
    if (
        asset_path.resolve() == DEMO_ANIMATION_DIR.resolve()
        and not (asset_path / "manifest.json").is_file()
    ):
        animation = {
            "healthy": True,
            "status": "will_generate_on_first_start",
            "style": "refined-pixel-art",
            "clips": 0,
            "frames": 0,
        }
    else:
        try:
            asset_report = animation_report(asset_path)
            animation = {
                "healthy": True,
                "status": "ok",
                "style": asset_report["style"],
                "clips": asset_report["clips"],
                "frames": asset_report["frames"],
            }
        except (OSError, TypeError, ValueError) as error:
            animation = {
                "healthy": False,
                "status": "error",
                "error_type": type(error).__name__,
            }
    database_ok = report.healthy or report.status in {"missing", "legacy"}
    healthy = database_ok and bool(animation["healthy"])
    payload = {
        "ok": healthy,
        "application": "LIFE-Mind",
        "version": __version__,
        "runtime": {
            "platform": platform.system().casefold(),
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "frozen": bool(getattr(sys, "frozen", False)),
        },
        "database": report.public_dict(),
        "backups": {
            "valid_count": len(backups),
            "restore_available": bool(backups),
        },
        "animation": animation,
        "privacy": "No paths, memory text, dialogue, API keys, or model endpoints included.",
    }
    return payload, healthy


def _backup_database(database_path: Path) -> Path:
    report = inspect_database(database_path, full=True)
    if not report.exists:
        raise DatabaseReliabilityError("数据库尚未创建，没有可备份的数据")
    if not report.healthy and report.status != "legacy":
        raise DatabaseReliabilityError(f"数据库未通过完整性检查：{report.status}")
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        return create_atomic_backup(connection, database_path)
    finally:
        connection.close()


def main() -> int:
    args = parse_args()
    if args.reset_config and args.config_path.exists():
        args.config_path.unlink()

    asset = args.asset
    database_path = Path(args.db_path) if args.db_path is not None else DEFAULT_DB_PATH
    if args.doctor:
        payload, healthy = _doctor_payload(database_path, asset)
        _print_json(payload)
        return 0 if healthy else 1
    if args.backup_now:
        try:
            backup = _backup_database(database_path)
        except (OSError, sqlite3.Error, DatabaseReliabilityError) as error:
            _print_json(
                {
                    "ok": False,
                    "operation": "backup",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }
            )
            return 1
        _print_json({"ok": True, "operation": "backup", "backup_file": backup.name})
        return 0
    if args.restore_latest_backup:
        try:
            restored, quarantine = restore_latest_backup(database_path)
        except (OSError, sqlite3.Error, DatabaseReliabilityError) as error:
            _print_json(
                {
                    "ok": False,
                    "operation": "restore",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }
            )
            return 1
        _print_json(
            {
                "ok": True,
                "operation": "restore",
                "restored_backup": restored.name,
                "previous_database_quarantined": quarantine is not None,
            }
        )
        return 0
    if asset.resolve() == DEMO_ANIMATION_DIR.resolve() and not (asset / "manifest.json").is_file():
        ensure_demo_character(asset)
    if args.check or args.release_check:
        report = animation_report(asset)
        if args.release_check:
            from life_mind.ai import APISecretStore
            from life_mind.apps.system_tray import PYSTRAY_AVAILABLE

            try:
                if not PYSTRAY_AVAILABLE:
                    raise RuntimeError("系统托盘组件不可用")
                # Read a deliberately unused credential id. This proves the
                # Windows keyring backend is packaged without writing a secret.
                APISecretStore().get("life-mind-release-check-never-stored")
            except Exception as error:
                if sys.stderr is not None:
                    print(f"ERROR: 冻结版依赖自检失败：{error}", file=sys.stderr)
                return 1
            report["system_tray"] = "available"
            report["credential_store"] = "available"
        output = json.dumps(report, ensure_ascii=True, indent=2)
        # A PyInstaller windowed executable has no stdout stream. The exit code
        # still makes --check useful to CI and release smoke tests.
        if sys.stdout is not None:
            print(output)
        return 0

    run_desktop_pet(
        asset,
        config_path=args.config_path,
        mind_path=args.db_path,
        windowed=args.windowed,
        ui_qa_lightweight=args.ui_qa_lightweight,
        developer_mode=args.developer_mode,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
