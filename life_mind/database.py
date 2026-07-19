"""SQLite schema, health checks, backups, and local recovery helpers."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


APPLICATION_ID = 0x4C494645  # "LIFE"
CURRENT_SCHEMA_VERSION = 1
DEFAULT_BACKUP_RETENTION = 7
REQUIRED_TABLES = frozenset(
    {
        "memories",
        "events",
        "state",
        "source_permissions",
        "memory_search_index",
        "memory_dependencies",
        "memory_event_links",
        "memory_mind_event_links",
        "room_tasks",
        "daily_journal",
        "journal_memory_links",
        "mind_runtime_meta",
        "mind_events_v2",
        "schema_migrations",
    }
)


class DatabaseReliabilityError(RuntimeError):
    """Base error for a database that cannot safely be opened or changed."""


class UnsupportedSchemaVersion(DatabaseReliabilityError):
    """Raised when a newer application has already upgraded the database."""


@dataclass(frozen=True, slots=True)
class DatabaseHealthReport:
    exists: bool
    healthy: bool
    status: str
    schema_version: int | None
    supported_schema_version: int
    application_id: int | None
    size_bytes: int
    table_count: int
    event_count: int | None
    memory_count: int | None
    foreign_key_violations: int | None
    invalid_json_values: int | None
    missing_required_tables: int | None
    detail: str

    def public_dict(self) -> dict[str, object]:
        """Return diagnostics without paths, content, account names, or secrets."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class DatabaseRecoveryResult:
    status: str
    notice: str
    quarantine_dir: Path | None = None
    restored_from: Path | None = None


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def backup_directory(path: Path) -> Path:
    resolved = Path(path)
    if resolved.name.casefold() == "life-mind.db":
        return resolved.parent / "backups"
    return resolved.parent / f"{resolved.stem}-backups"


def recovery_directory(path: Path) -> Path:
    return Path(path).parent / "recovery"


def _sidecar_paths(path: Path) -> tuple[Path, ...]:
    return (Path(path), Path(f"{path}-wal"), Path(f"{path}-shm"))


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _safe_count(connection: sqlite3.Connection, table: str, where: str = "") -> int | None:
    if not _table_exists(connection, table):
        return None
    return int(connection.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0])


def inspect_database(path: Path, *, full: bool = False) -> DatabaseHealthReport:
    """Inspect a SQLite file read-only and never include private rows in the result."""

    database = Path(path)
    if not database.is_file():
        return DatabaseHealthReport(
            exists=False,
            healthy=True,
            status="missing",
            schema_version=None,
            supported_schema_version=CURRENT_SCHEMA_VERSION,
            application_id=None,
            size_bytes=0,
            table_count=0,
            event_count=None,
            memory_count=None,
            foreign_key_violations=None,
            invalid_json_values=None,
            missing_required_tables=None,
            detail="数据库尚未创建；首次启动会创建新的本地数据库。",
        )

    connection: sqlite3.Connection | None = None
    try:
        uri = database.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        check_name = "integrity_check" if full else "quick_check"
        check_rows = connection.execute(f"PRAGMA {check_name}").fetchall()
        check_ok = bool(check_rows) and all(str(row[0]).casefold() == "ok" for row in check_rows)
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        table_count = len(table_names)
        violations = 0
        for violations, _row in enumerate(
            connection.execute("PRAGMA foreign_key_check"), start=1
        ):
            if violations >= 100:
                break
        json_columns = {
            "state": ("value_json",),
            "events": ("payload_json",),
            "mind_runtime_meta": ("value_json",),
            "mind_events_v2": ("event_json", "trace_json"),
            "memories": ("allowed_uses_json",),
        }
        invalid_json = 0
        for table, columns in json_columns.items():
            if table not in table_names:
                continue
            available_columns = {
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for column in columns:
                if column not in available_columns:
                    continue
                invalid_json += int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE json_valid({column})=0"
                    ).fetchone()[0]
                )
        recognizable_legacy = not table_names or bool(
            table_names.intersection({"memories", "events", "state", "mind_events_v2"})
        )
        app_ok = application_id == APPLICATION_ID or (
            application_id == 0 and recognizable_legacy
        )
        version_ok = schema_version <= CURRENT_SCHEMA_VERSION
        missing_required = (
            len(REQUIRED_TABLES.difference(table_names)) if schema_version >= 1 else 0
        )
        healthy = (
            check_ok
            and app_ok
            and version_ok
            and violations == 0
            and invalid_json == 0
            and missing_required == 0
        )
        if not check_ok:
            status, detail = "corrupt", "SQLite 完整性检查未通过。"
        elif not app_ok:
            status, detail = "foreign_database", "文件不是 LIFE-Mind 数据库。"
        elif not version_ok:
            status, detail = "newer_schema", "数据库来自更新版本的 LIFE-Mind。"
        elif violations:
            status, detail = "foreign_key_error", "数据库存在外键一致性问题。"
        elif invalid_json:
            status, detail = "invalid_json", "数据库存在无法解析的结构化字段。"
        elif missing_required:
            status, detail = "incomplete_schema", "数据库缺少当前版本要求的数据表。"
        elif schema_version == 0:
            status, detail = "legacy", "旧版数据库可迁移到当前架构。"
        else:
            status, detail = "ok", "数据库完整性与架构版本正常。"
        return DatabaseHealthReport(
            exists=True,
            healthy=healthy,
            status=status,
            schema_version=schema_version,
            supported_schema_version=CURRENT_SCHEMA_VERSION,
            application_id=application_id,
            size_bytes=database.stat().st_size,
            table_count=table_count,
            event_count=_safe_count(connection, "mind_events_v2"),
            memory_count=_safe_count(connection, "memories", "WHERE active=1"),
            foreign_key_violations=violations,
            invalid_json_values=invalid_json,
            missing_required_tables=missing_required,
            detail=detail,
        )
    except (OSError, sqlite3.DatabaseError) as error:
        return DatabaseHealthReport(
            exists=True,
            healthy=False,
            status="unreadable",
            schema_version=None,
            supported_schema_version=CURRENT_SCHEMA_VERSION,
            application_id=None,
            size_bytes=database.stat().st_size if database.exists() else 0,
            table_count=0,
            event_count=None,
            memory_count=None,
            foreign_key_violations=None,
            invalid_json_values=None,
            missing_required_tables=None,
            detail=f"SQLite 无法读取数据库：{type(error).__name__}",
        )
    finally:
        if connection is not None:
            connection.close()


def _ensure_column(
    connection: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    columns = {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def migrate_database(connection: sqlite3.Connection, *, now: Callable[[], str]) -> int:
    """Atomically establish the v1 schema and record a forward migration baseline."""

    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    if current > CURRENT_SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(
            f"数据库架构版本 {current} 高于当前支持的 {CURRENT_SCHEMA_VERSION}"
        )
    if application_id not in (0, APPLICATION_ID):
        raise DatabaseReliabilityError("拒绝打开不属于 LIFE-Mind 的 SQLite 数据库")
    if application_id == 0:
        existing_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        recognizable = existing_tables.intersection(
            {"memories", "events", "state", "mind_events_v2"}
        )
        if existing_tables and not recognizable:
            raise DatabaseReliabilityError(
                "拒绝把未标记的第三方 SQLite 文件迁移为 LIFE-Mind 数据库"
            )

    statements = (
        """CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, memory_key TEXT NOT NULL UNIQUE,
            content TEXT NOT NULL, category TEXT NOT NULL, confidence REAL NOT NULL,
            importance REAL NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)""",
        """CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL, created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS state (
            state_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS source_permissions (
            source_key TEXT PRIMARY KEY, level INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0, description TEXT NOT NULL,
            updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS memory_search_index (
            memory_id INTEGER PRIMARY KEY, search_text TEXT NOT NULL,
            FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE)""",
        """CREATE TABLE IF NOT EXISTS memory_dependencies (
            memory_id INTEGER NOT NULL, source_memory_id INTEGER NOT NULL,
            PRIMARY KEY(memory_id, source_memory_id),
            FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE,
            FOREIGN KEY(source_memory_id) REFERENCES memories(id) ON DELETE CASCADE)""",
        """CREATE INDEX IF NOT EXISTS idx_memory_dependencies_source
            ON memory_dependencies(source_memory_id)""",
        """CREATE TABLE IF NOT EXISTS memory_event_links (
            memory_id INTEGER NOT NULL, event_id INTEGER NOT NULL,
            PRIMARY KEY(memory_id, event_id),
            FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE,
            FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE)""",
        """CREATE TABLE IF NOT EXISTS memory_mind_event_links (
            memory_id INTEGER NOT NULL, mind_event_id TEXT NOT NULL,
            PRIMARY KEY(memory_id, mind_event_id),
            FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE)""",
        """CREATE TABLE IF NOT EXISTS room_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS daily_journal (
            day TEXT PRIMARY KEY, content TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, valid INTEGER NOT NULL DEFAULT 1)""",
        """CREATE TABLE IF NOT EXISTS journal_memory_links (
            day TEXT NOT NULL, memory_id INTEGER NOT NULL,
            PRIMARY KEY(day, memory_id),
            FOREIGN KEY(day) REFERENCES daily_journal(day) ON DELETE CASCADE,
            FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE)""",
        """CREATE TABLE IF NOT EXISTS mind_runtime_meta (
            meta_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS mind_events_v2 (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
            event_json TEXT NOT NULL, trace_json TEXT NOT NULL, created_at TEXT NOT NULL)""",
        """CREATE INDEX IF NOT EXISTS idx_mind_events_v2_created
            ON mind_events_v2(sequence)""",
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL,
            description TEXT NOT NULL)""",
    )
    permission_defaults = {
        "user_input": (0, 1, "用户主动输入"),
        "ai_interpretation": (0, 1, "由已授权本地记忆推导的 AI 解释"),
        "ai_reflection": (0, 1, "由已授权证据生成的本地反思"),
        "validated_reflection": (0, 1, "通过规则验证的角色反思"),
        "manual_import": (1, 0, "用户手动选择导入的文本或文件"),
        "app_status": (2, 0, "明确开启的应用状态"),
    }
    state_defaults: dict[str, object] = {
        "energy": 0.78,
        "mood": 0.68,
        "trust": 0.55,
        "interaction_count": 0,
        "last_seen": now(),
        "dominant_emotion": "calm",
        "emotion_cause": "启动后保持平静",
        "offline_summary": "这是本次启动后的第一段安静时光。",
        "room_locked": False,
    }

    try:
        connection.execute("BEGIN IMMEDIATE")
        for statement in statements:
            connection.execute(statement)
        _ensure_column(connection, "memories", "privacy", "TEXT NOT NULL DEFAULT 'private'")
        _ensure_column(
            connection,
            "memories",
            "allowed_uses_json",
            "TEXT NOT NULL DEFAULT '[\"recall\",\"model_context\",\"room_display\",\"export\"]'",
        )
        _ensure_column(
            connection, "memories", "review_required", "INTEGER NOT NULL DEFAULT 0"
        )
        _ensure_column(connection, "memories", "deleted_at", "TEXT")
        _ensure_column(
            connection, "daily_journal", "importance", "REAL NOT NULL DEFAULT 0.0"
        )
        _ensure_column(
            connection, "daily_journal", "public_content", "TEXT NOT NULL DEFAULT ''"
        )
        applied_at = now()
        for source_key, (level, enabled, description) in permission_defaults.items():
            connection.execute(
                """INSERT OR IGNORE INTO source_permissions(
                    source_key, level, enabled, description, updated_at)
                    VALUES (?, ?, ?, ?, ?)""",
                (source_key, level, enabled, description, applied_at),
            )
        connection.execute(
            """INSERT OR REPLACE INTO memory_search_index(memory_id, search_text)
            SELECT id, lower(memory_key || ' ' || category || ' ' || content)
            FROM memories WHERE active=1"""
        )
        for key, value in state_defaults.items():
            connection.execute(
                """INSERT OR IGNORE INTO state(state_key, value_json, updated_at)
                VALUES (?, ?, ?)""",
                (key, json.dumps(value, ensure_ascii=False), now()),
            )
        connection.execute(
            """INSERT OR IGNORE INTO schema_migrations(version, applied_at, description)
            VALUES (1, ?, 'Establish versioned LIFE-Mind schema baseline')""",
            (applied_at,),
        )
        connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version={CURRENT_SCHEMA_VERSION}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return current


def create_atomic_backup(
    connection: sqlite3.Connection,
    database_path: Path,
    *,
    directory: Path | None = None,
    retention: int = DEFAULT_BACKUP_RETENTION,
) -> Path:
    """Create a verified SQLite snapshot and atomically publish it as a backup."""

    source = Path(database_path)
    target_dir = Path(directory) if directory is not None else backup_directory(source)
    target_dir.mkdir(parents=True, exist_ok=True)
    final = target_dir / f"{source.stem}-{utc_stamp()}-{uuid.uuid4().hex[:8]}.db"
    temporary = final.with_suffix(".tmp")
    destination: sqlite3.Connection | None = None
    try:
        destination = sqlite3.connect(temporary)
        connection.backup(destination)
        destination.commit()
        destination.close()
        destination = None
        report = inspect_database(temporary, full=True)
        if not report.healthy and report.status != "legacy":
            raise DatabaseReliabilityError(f"新备份未通过完整性检查：{report.status}")
        os.replace(temporary, final)
    except BaseException:
        if destination is not None:
            destination.close()
        temporary.unlink(missing_ok=True)
        raise

    backups = sorted(
        target_dir.glob(f"{source.stem}-*.db"),
        key=lambda item: item.stat().st_mtime_ns,
        reverse=True,
    )
    for stale in backups[max(1, int(retention)) :]:
        stale.unlink(missing_ok=True)
    return final


def quarantine_database(path: Path, *, reason: str) -> Path:
    database = Path(path)
    root = recovery_directory(database)
    target = root / f"{reason}-{utc_stamp()}-{uuid.uuid4().hex[:8]}"
    target.mkdir(parents=True, exist_ok=False)
    existing = [item for item in _sidecar_paths(database) if item.exists()]
    if not existing:
        target.rmdir()
        raise FileNotFoundError(database)
    moved: list[tuple[Path, Path]] = []
    try:
        for item in existing:
            destination = target / item.name
            os.replace(item, destination)
            moved.append((item, destination))
    except BaseException:
        for original, destination in reversed(moved):
            if destination.exists() and not original.exists():
                try:
                    os.replace(destination, original)
                except OSError:
                    pass
        try:
            target.rmdir()
        except OSError:
            pass
        raise
    return target


def _copy_verified_database(source: Path, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.restore.tmp")
    try:
        shutil.copy2(source, temporary)
        report = inspect_database(temporary, full=True)
        if not report.healthy and report.status != "legacy":
            raise DatabaseReliabilityError(f"备份不可用：{report.status}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def valid_backups(path: Path, *, directory: Path | None = None) -> list[Path]:
    database = Path(path)
    target_dir = Path(directory) if directory is not None else backup_directory(database)
    if not target_dir.is_dir():
        return []
    candidates = sorted(
        target_dir.glob(f"{database.stem}-*.db"),
        key=lambda item: item.stat().st_mtime_ns,
        reverse=True,
    )
    return [
        item
        for item in candidates
        if (report := inspect_database(item, full=True)).healthy or report.status == "legacy"
    ]


def restore_latest_backup(
    path: Path,
    *,
    directory: Path | None = None,
    quarantine_current: bool = True,
) -> tuple[Path, Path | None]:
    database = Path(path)
    backups = valid_backups(database, directory=directory)
    if not backups:
        raise DatabaseReliabilityError("没有找到通过完整性检查的数据库备份")
    quarantine = None
    if quarantine_current and any(item.exists() for item in _sidecar_paths(database)):
        quarantine = quarantine_database(database, reason="manual-restore")
    database.parent.mkdir(parents=True, exist_ok=True)
    _copy_verified_database(backups[0], database)
    return backups[0], quarantine


def ensure_database_available(
    path: Path, *, directory: Path | None = None
) -> DatabaseRecoveryResult:
    """Quarantine physical corruption and restore the newest valid snapshot if possible."""

    database = Path(path)
    report = inspect_database(database)
    if not report.exists:
        return DatabaseRecoveryResult("new", report.detail)
    if report.healthy or report.status == "legacy":
        return DatabaseRecoveryResult("healthy", report.detail)
    if report.status in {"newer_schema", "foreign_database"}:
        raise DatabaseReliabilityError(report.detail)

    quarantine = quarantine_database(database, reason="corrupt")
    backups = valid_backups(database, directory=directory)
    if backups:
        _copy_verified_database(backups[0], database)
        return DatabaseRecoveryResult(
            "restored",
            "检测到数据库损坏，已隔离原文件并恢复最近的有效备份。",
            quarantine_dir=quarantine,
            restored_from=backups[0],
        )
    return DatabaseRecoveryResult(
        "reset",
        "检测到数据库损坏，已隔离原文件；没有有效备份，因此创建新的数据库。",
        quarantine_dir=quarantine,
    )


__all__ = (
    "APPLICATION_ID",
    "CURRENT_SCHEMA_VERSION",
    "DatabaseHealthReport",
    "DatabaseRecoveryResult",
    "DatabaseReliabilityError",
    "UnsupportedSchemaVersion",
    "backup_directory",
    "create_atomic_backup",
    "ensure_database_available",
    "inspect_database",
    "migrate_database",
    "quarantine_database",
    "restore_latest_backup",
    "valid_backups",
)
