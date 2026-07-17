"""Open an isolated Stage 4 personal-room preview for visual QA."""

from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from life_mind.apps.private_room import PrivateRoomWindow
from life_mind.mind import MindEngine
from life_mind.simulator import load_events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, default=PROJECT_ROOT / "tmp" / "growth-room-preview.db"
    )
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        args.db.with_name(args.db.name + suffix).unlink(missing_ok=True)

    engine = MindEngine(args.db)
    for event in load_events(PROJECT_ROOT / "simulations" / "demo_growth.json"):
        engine.runtime.apply(event)
    engine._sync_runtime_state()
    engine.store_memory(
        "今天第一次把只为自己画画的时刻写进了公开日记",
        source="user_input",
        memory_key="preview.important-diary",
        importance=0.95,
    )
    engine.connection.commit()

    root = tk.Tk()
    root.withdraw()

    def close() -> None:
        engine.close()
        engine.connection.close()
        root.destroy()

    PrivateRoomWindow(root, engine, on_close=close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
