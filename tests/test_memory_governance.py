from __future__ import annotations

import json
import shutil
import sqlite3
import unittest
import uuid
from pathlib import Path

from life_mind.database import backup_directory
from life_mind.mind import MindEngine


class MemoryGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(__file__).with_name(
            f"life-mind-memory-governance-test-{uuid.uuid4().hex}.db"
        )
        self.engine = MindEngine(self.path)

    def tearDown(self) -> None:
        self.engine.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
        shutil.rmtree(backup_directory(self.path), ignore_errors=True)

    def test_unapproved_source_never_enters_model_context(self) -> None:
        with self.assertRaises(PermissionError):
            self.engine.store_memory("手动导入的私人句子", source="manual_import")

        self.engine.set_source_permission("manual_import", True)
        record = self.engine.store_memory("手动导入的私人句子", source="manual_import")
        self.assertIn(record.id, {item.id for item in self.engine.memories_for_use("model_context")})

        self.engine.set_source_permission("manual_import", False)
        self.assertIsNotNone(self.engine.memory(record.id))
        self.assertNotIn(
            record.id, {item.id for item in self.engine.memories_for_use("model_context")}
        )
        self.assertNotIn(record.id, {item.id for item in self.engine.recall("私人句子")})

    def test_delete_cascades_to_events_index_derived_memory_and_journal(self) -> None:
        self.engine.process_user_text("请记住：秘密代号是晨光。")
        root = next(item for item in self.engine.memories() if "秘密代号" in item.content)
        other = self.engine.store_memory(
            "另一个独立证据",
            source="user_input",
            memory_key="test.other",
            importance=0.80,
        )
        only_child = self.engine.store_memory(
            "只由秘密代号推导出的摘要",
            source="ai_interpretation",
            memory_key="test.only-child",
            derived_from=(root.id,),
        )
        grandchild = self.engine.store_memory(
            "只由上一条摘要继续推导",
            source="ai_interpretation",
            memory_key="test.grandchild",
            derived_from=(only_child.id,),
        )
        shared_child = self.engine.store_memory(
            "同时由两条证据支持",
            source="ai_interpretation",
            memory_key="test.shared-child",
            derived_from=(root.id, other.id),
        )
        journal_before = self.engine.ensure_daily_journal()
        self.assertIn("秘密代号", journal_before.content)

        result = self.engine.delete_memory(root.id)

        self.assertEqual(set(result.deleted_ids), {root.id, only_child.id, grandchild.id})
        self.assertEqual(result.downgraded_ids, (shared_child.id,))
        self.assertIsNone(self.engine.memory(root.id))
        reviewed = self.engine.memory(shared_child.id)
        self.assertIsNotNone(reviewed)
        self.assertTrue(reviewed.review_required)
        self.assertNotIn(
            shared_child.id,
            {item.id for item in self.engine.memories_for_use("model_context")},
        )
        indexed = self.engine.connection.execute(
            "SELECT memory_id FROM memory_search_index WHERE memory_id IN (?, ?, ?, ?)",
            (root.id, only_child.id, grandchild.id, shared_child.id),
        ).fetchall()
        self.assertEqual(indexed, [])
        deleted_row = self.engine.connection.execute(
            "SELECT content, active FROM memories WHERE id=?", (root.id,)
        ).fetchone()
        self.assertEqual(deleted_row["content"], "[已删除]")
        self.assertEqual(deleted_row["active"], 0)

        legacy_payloads = [
            str(row[0])
            for row in self.engine.connection.execute(
                "SELECT payload_json FROM events WHERE id IN "
                "(SELECT event_id FROM memory_event_links WHERE memory_id=?)",
                (root.id,),
            ).fetchall()
        ]
        self.assertTrue(legacy_payloads)
        self.assertTrue(all("秘密代号" not in payload for payload in legacy_payloads))
        mind_payloads = [
            str(row[0])
            for row in self.engine.connection.execute(
                "SELECT event_json FROM mind_events_v2 WHERE event_id IN "
                "(SELECT mind_event_id FROM memory_mind_event_links WHERE memory_id=?)",
                (root.id,),
            ).fetchall()
        ]
        self.assertTrue(mind_payloads)
        self.assertTrue(all("秘密代号" not in payload for payload in mind_payloads))
        journal_after = self.engine.ensure_daily_journal(journal_before.day)
        self.assertNotIn("秘密代号", journal_after.content)

    def test_revoke_source_can_delete_history_and_export_excludes_it(self) -> None:
        self.engine.set_source_permission("manual_import", True)
        record = self.engine.store_memory("不应留在导出中的内容", source="manual_import")
        results = self.engine.set_source_permission(
            "manual_import", False, delete_history=True
        )
        self.assertTrue(results)
        self.assertIsNone(self.engine.memory(record.id))
        exported = self.engine.memory_export_bundle()
        serialized = json.dumps(exported, ensure_ascii=False)
        self.assertNotIn("不应留在导出中的内容", serialized)

    def test_public_room_is_a_black_box_while_private_data_remains_manageable(self) -> None:
        self.engine.process_user_text("我喜欢安静的音乐。")
        self.engine.store_memory(
            "今天第一次认真说起喜欢安静的音乐",
            source="user_input",
            memory_key="test.important-journal",
            importance=0.95,
        )
        task = self.engine.add_room_task("整理第一版回忆架")
        self.engine.set_room_task_status(task.id, "done")
        self.engine.set_room_locked(True)
        snapshot = self.engine.private_room_snapshot()

        self.assertTrue(snapshot["locked"])
        self.assertEqual(self.engine.room_tasks()[0].status, "done")
        self.assertTrue(self.engine.memories())
        self.assertTrue(snapshot["important_journal"])
        public_diary = json.dumps(snapshot["important_journal"], ensure_ascii=False)
        for hidden_text in ("精力", "成长阶段", "active_conflict", "最近的行动"):
            self.assertNotIn(hidden_text, public_diary)
        self.assertEqual(
            set(snapshot), {"locked", "mood", "affection", "important_journal"}
        )
        self.assertTrue(
            all(set(entry) == {"day", "content"} for entry in snapshot["important_journal"])
        )
        for hidden in (
            "growth",
            "visible_growth",
            "relations",
            "permissions",
            "memories",
            "tasks",
            "activity",
            "state",
        ):
            self.assertNotIn(hidden, snapshot)
        self.engine.set_room_locked(False)
        self.assertFalse(self.engine.private_room_snapshot()["locked"])


class MemorySchemaMigrationTests(unittest.TestCase):
    def test_existing_stage_one_database_is_migrated_in_place(self) -> None:
        path = Path(__file__).with_name(
            f"life-mind-memory-migration-test-{uuid.uuid4().hex}.db"
        )
        connection = sqlite3.connect(path)
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
                'legacy.fact', '阶段一保留下来的记忆', 'explicit', 0.9, 0.8,
                'user_input', '2026-07-17T00:00:00+00:00',
                '2026-07-17T00:00:00+00:00', 1
            );
            CREATE TABLE daily_journal (
                day TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                valid INTEGER NOT NULL DEFAULT 1
            );
            INSERT INTO daily_journal(day, content, created_at, updated_at, valid)
            VALUES (
                '2026-07-16',
                '旧界面泄露：精力 80%，成长阶段 3，最近的行动是 work。',
                '2026-07-16T00:00:00+00:00',
                '2026-07-16T00:00:00+00:00',
                1
            );
            """
        )
        connection.commit()
        connection.close()
        try:
            engine = MindEngine(path)
            migrated = engine.memories()[0]
            self.assertEqual(migrated.content, "阶段一保留下来的记忆")
            self.assertIn("model_context", migrated.allowed_uses)
            self.assertIn(migrated.id, {item.id for item in engine.recall("阶段一保留")})
            journal_columns = {
                str(row["name"])
                for row in engine.connection.execute("PRAGMA table_info(daily_journal)")
            }
            self.assertIn("importance", journal_columns)
            self.assertIn("public_content", journal_columns)
            public = json.dumps(engine.public_room_snapshot(), ensure_ascii=False)
            self.assertNotIn("旧界面泄露", public)
            engine.close()
            engine.connection.close()
        finally:
            for suffix in ("", "-wal", "-shm"):
                Path(str(path) + suffix).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
