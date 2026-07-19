from __future__ import annotations

import shutil
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

from life_mind.database import inspect_database
from life_mind.mind import MindEngine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKER = PROJECT_ROOT / "tests" / "helpers" / "database_crash_worker.py"


class DatabaseCrashRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = PROJECT_ROOT / "tmp" / f"crash-test-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.database = self.root / "crash.db"
        self.ready = self.root / "ready.txt"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_force_kill_preserves_commit_and_rolls_back_open_transaction(self) -> None:
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                str(WORKER),
                "--db",
                str(self.database),
                "--ready",
                str(self.ready),
            ],
            cwd=PROJECT_ROOT,
        )
        try:
            deadline = time.monotonic() + 20.0
            while not self.ready.is_file() and time.monotonic() < deadline:
                if process.poll() is not None:
                    self.fail(f"异常退出测试子进程提前结束：{process.returncode}")
                time.sleep(0.05)
            self.assertTrue(self.ready.is_file(), "子进程未进入待强制终止事务")
            process.kill()
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)

        report = inspect_database(self.database, full=True)
        self.assertTrue(report.healthy, report)
        reopened = MindEngine(self.database, auto_backup=False)
        event_ids = [event.event_id for event in reopened.runtime.events]
        self.assertEqual(event_ids, ["crash-probe-committed"])
        self.assertEqual(reopened.runtime.event_count(), 1)
        reopened.close()


if __name__ == "__main__":
    unittest.main()
