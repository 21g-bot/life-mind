from __future__ import annotations

import json
import shutil
import sqlite3
import unittest
import uuid
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from life_mind.database import (
    APPLICATION_ID,
    CURRENT_SCHEMA_VERSION,
    DatabaseReliabilityError,
    create_atomic_backup,
    inspect_database,
    migrate_database,
    quarantine_database,
    restore_latest_backup,
)
from life_mind.demo_character import ensure_demo_character
from life_mind.mind import MindEngine
from run_pet import _doctor_payload, parse_args


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DatabaseReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = PROJECT_ROOT / "tmp" / f"database-reliability-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.database = self.root / "life-mind.db"
        self.backups = self.root / "backups"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_legacy_database_is_versioned_without_losing_memory(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_key TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                confidence REAL NOT NULL,
                importance REAL NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
            INSERT INTO memories(
                memory_key, content, category, confidence, importance,
                source, created_at, updated_at, active
            ) VALUES (
                'legacy.safe', '应当保留的旧记忆', 'explicit', 0.9, 0.8,
                'user_input', '2026-07-17T00:00:00+00:00',
                '2026-07-17T00:00:00+00:00', 1
            );
            """
        )
        connection.commit()
        connection.close()

        engine = MindEngine(
            self.database,
            auto_backup=True,
            backup_dir=self.backups,
        )
        self.assertEqual(engine.memories()[0].content, "应当保留的旧记忆")
        self.assertEqual(
            engine.connection.execute("PRAGMA user_version").fetchone()[0],
            CURRENT_SCHEMA_VERSION,
        )
        self.assertEqual(
            engine.connection.execute("PRAGMA application_id").fetchone()[0],
            APPLICATION_ID,
        )
        migration = engine.connection.execute(
            "SELECT description FROM schema_migrations WHERE version=1"
        ).fetchone()
        self.assertIsNotNone(migration)
        engine.close()
        self.assertGreaterEqual(len(list(self.backups.glob("*.db"))), 1)

    def test_newer_schema_is_rejected_without_quarantining_it(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute(f"PRAGMA user_version={CURRENT_SCHEMA_VERSION + 1}")
        connection.commit()
        connection.close()

        with self.assertRaises(DatabaseReliabilityError):
            MindEngine(self.database, auto_backup=False)

        self.assertTrue(self.database.exists())
        self.assertFalse((self.root / "recovery").exists())

    def test_unmarked_foreign_sqlite_file_is_never_claimed_as_life_mind_data(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("CREATE TABLE unrelated_app(secret TEXT NOT NULL)")
        connection.execute("INSERT INTO unrelated_app(secret) VALUES ('keep me')")
        connection.commit()
        connection.close()

        report = inspect_database(self.database, full=True)
        self.assertEqual(report.status, "foreign_database")
        with self.assertRaises(DatabaseReliabilityError):
            MindEngine(self.database, auto_backup=False)

        connection = sqlite3.connect(self.database)
        self.assertEqual(
            connection.execute("SELECT secret FROM unrelated_app").fetchone()[0],
            "keep me",
        )
        connection.close()
        self.assertFalse((self.root / "recovery").exists())

    def test_failed_migration_rolls_back_every_schema_change(self) -> None:
        connection = sqlite3.connect(self.database)
        with patch(
            "life_mind.database._ensure_column",
            side_effect=RuntimeError("forced migration failure"),
        ), self.assertRaises(RuntimeError):
            migrate_database(connection, now=lambda: "2026-07-19T00:00:00+00:00")
        table_count = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        self.assertEqual(table_count, 0)
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
        connection.close()

    def test_partial_quarantine_failure_moves_already_moved_files_back(self) -> None:
        self.database.write_bytes(b"database bytes")
        wal = Path(f"{self.database}-wal")
        wal.write_bytes(b"wal bytes")
        from life_mind import database as database_module

        real_replace = database_module.os.replace
        calls = 0

        def fail_second_replace(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("forced sidecar move failure")
            return real_replace(source, destination)

        with patch("life_mind.database.os.replace", side_effect=fail_second_replace):
            with self.assertRaises(OSError):
                quarantine_database(self.database, reason="forced")

        self.assertEqual(self.database.read_bytes(), b"database bytes")
        self.assertEqual(wal.read_bytes(), b"wal bytes")

    def test_corruption_is_quarantined_and_latest_backup_is_restored(self) -> None:
        engine = MindEngine(
            self.database,
            auto_backup=True,
            backup_dir=self.backups,
        )
        engine.process_user_text("请记住：蓝色纸条是重要线索")
        expected_events = engine.runtime.event_count()
        expected_memories = [record.content for record in engine.memories()]
        engine.close()
        self.assertTrue(list(self.backups.glob("*.db")))

        self.database.write_bytes(b"this is not sqlite")
        restored = MindEngine(
            self.database,
            auto_backup=False,
            backup_dir=self.backups,
        )
        self.assertEqual(restored.startup_recovery.status, "restored")
        self.assertEqual(restored.runtime.event_count(), expected_events)
        self.assertEqual([record.content for record in restored.memories()], expected_memories)
        self.assertTrue(restored.startup_recovery.quarantine_dir.is_dir())
        restored.close()

    def test_corruption_without_backup_is_isolated_before_new_database(self) -> None:
        self.database.write_bytes(b"broken sqlite payload")

        engine = MindEngine(
            self.database,
            auto_backup=False,
            backup_dir=self.backups,
        )
        self.assertEqual(engine.startup_recovery.status, "reset")
        self.assertEqual(engine.runtime.event_count(), 0)
        self.assertTrue(engine.startup_recovery.quarantine_dir.is_dir())
        self.assertTrue(inspect_database(self.database, full=True).healthy)
        engine.close()

    def test_invalid_critical_json_is_treated_as_recoverable_corruption(self) -> None:
        engine = MindEngine(
            self.database,
            auto_backup=True,
            backup_dir=self.backups,
        )
        engine.process_user_text("普通对话用于创建有效快照")
        expected_events = engine.runtime.event_count()
        engine.close()

        connection = sqlite3.connect(self.database)
        connection.execute(
            "UPDATE state SET value_json='{' WHERE state_key='energy'"
        )
        connection.commit()
        connection.close()
        report = inspect_database(self.database, full=True)
        self.assertEqual(report.status, "invalid_json")
        self.assertEqual(report.invalid_json_values, 1)

        recovered = MindEngine(
            self.database,
            auto_backup=False,
            backup_dir=self.backups,
        )
        self.assertEqual(recovered.startup_recovery.status, "restored")
        self.assertEqual(recovered.runtime.event_count(), expected_events)
        recovered.close()

    def test_missing_required_table_restores_backup_instead_of_silently_recreating(self) -> None:
        engine = MindEngine(
            self.database,
            auto_backup=True,
            backup_dir=self.backups,
        )
        engine.process_user_text("普通对话用于架构恢复")
        expected_events = engine.runtime.event_count()
        engine.close()

        connection = sqlite3.connect(self.database)
        connection.execute("DROP TABLE room_tasks")
        connection.commit()
        connection.close()
        report = inspect_database(self.database, full=True)
        self.assertEqual(report.status, "incomplete_schema")
        self.assertEqual(report.missing_required_tables, 1)

        recovered = MindEngine(
            self.database,
            auto_backup=False,
            backup_dir=self.backups,
        )
        self.assertEqual(recovered.startup_recovery.status, "restored")
        self.assertEqual(recovered.runtime.event_count(), expected_events)
        recovered.close()

    def test_manual_restore_quarantines_the_current_database(self) -> None:
        engine = MindEngine(
            self.database,
            auto_backup=True,
            backup_dir=self.backups,
        )
        engine.process_user_text("请记住：备份中的原始内容")
        engine.close()
        original_backup = sorted(self.backups.glob("*.db"))[-1]

        changed = MindEngine(self.database, auto_backup=False, backup_dir=self.backups)
        changed.process_user_text("请记住：恢复前新增内容")
        changed.close()
        restored, quarantine = restore_latest_backup(
            self.database, directory=self.backups
        )

        self.assertEqual(restored, original_backup)
        self.assertIsNotNone(quarantine)
        self.assertTrue(quarantine.is_dir())
        reopened = MindEngine(self.database, auto_backup=False, backup_dir=self.backups)
        contents = [record.content for record in reopened.memories()]
        self.assertIn("备份中的原始内容", contents)
        self.assertNotIn("恢复前新增内容", contents)
        reopened.close()

    def test_invalid_newest_backup_is_skipped_during_recovery(self) -> None:
        engine = MindEngine(
            self.database,
            auto_backup=False,
            backup_dir=self.backups,
        )
        engine.process_user_text("请记住：较早的有效备份")
        older = engine.backup_now()
        engine.process_user_text("请记住：只存在于损坏的新备份")
        newest = engine.backup_now()
        engine.close()
        newest.write_bytes(b"invalid newest backup")
        self.database.write_bytes(b"invalid live database")

        recovered = MindEngine(
            self.database,
            auto_backup=False,
            backup_dir=self.backups,
        )
        contents = [record.content for record in recovered.memories()]
        self.assertEqual(recovered.startup_recovery.restored_from, older)
        self.assertIn("较早的有效备份", contents)
        self.assertNotIn("只存在于损坏的新备份", contents)
        recovered.close()

    def test_backup_retention_keeps_only_the_seven_newest_snapshots(self) -> None:
        engine = MindEngine(
            self.database,
            auto_backup=False,
            backup_dir=self.backups,
        )
        for index in range(9):
            engine.process_user_text(f"普通对话 {index}")
            engine.backup_now()
        self.assertEqual(len(list(self.backups.glob("*.db"))), 7)
        self.assertEqual(list(self.backups.glob("*.tmp*")), [])
        engine.close()

    def test_backup_failure_does_not_prevent_a_clean_database_close(self) -> None:
        engine = MindEngine(
            self.database,
            auto_backup=True,
            backup_dir=self.backups,
        )
        with patch(
            "life_mind.mind.create_atomic_backup",
            side_effect=OSError("forced backup failure"),
        ):
            engine.close()
        self.assertTrue(engine._closed)
        self.assertIn("forced backup failure", engine.last_backup_error)

    def test_logically_corrupt_database_is_never_published_as_a_new_backup(self) -> None:
        engine = MindEngine(self.database, auto_backup=False, backup_dir=self.backups)
        engine.close()
        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE state SET value_json='{' WHERE state_key='mood'")
        connection.commit()
        with self.assertRaises(DatabaseReliabilityError):
            create_atomic_backup(connection, self.database, directory=self.backups)
        connection.close()
        self.assertFalse(list(self.backups.glob("*.db")))
        self.assertEqual(list(self.backups.glob("*.tmp*")), [])

    def test_doctor_report_is_useful_but_contains_no_private_content_or_path(self) -> None:
        engine = MindEngine(self.database, auto_backup=False, backup_dir=self.backups)
        engine.process_user_text("请记住：绝密诊断测试正文")
        engine.close()
        asset = self.root / "demo-character"
        ensure_demo_character(asset)

        payload, healthy = _doctor_payload(self.database, asset)
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertTrue(healthy)
        self.assertEqual(payload["database"]["memory_count"], 1)
        self.assertNotIn("绝密诊断测试正文", serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn('"endpoint":', serialized.casefold())
        self.assertNotIn('"api_key":', serialized.casefold())

    def test_doctor_accepts_missing_public_demo_before_first_start(self) -> None:
        missing_demo = self.root / "not-generated-yet"
        with patch("run_pet.DEMO_ANIMATION_DIR", missing_demo):
            payload, healthy = _doctor_payload(self.database, missing_demo)
        self.assertTrue(healthy)
        self.assertEqual(
            payload["animation"]["status"], "will_generate_on_first_start"
        )

    def test_maintenance_flags_are_mutually_exclusive(self) -> None:
        self.assertTrue(parse_args(["--doctor"]).doctor)
        self.assertTrue(parse_args(["--backup-now"]).backup_now)
        self.assertTrue(
            parse_args(["--restore-latest-backup"]).restore_latest_backup
        )
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["--doctor", "--backup-now"])
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["--doctor", "--reset-config"])
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["--doctor", "--check"])


if __name__ == "__main__":
    unittest.main()
