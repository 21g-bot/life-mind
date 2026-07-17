"""Create the neutral demo character used by a fresh open-source checkout."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from life_mind.apps.desktop_pet import DEMO_ANIMATION_DIR
from life_mind.demo_character import ensure_demo_character


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEMO_ANIMATION_DIR)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    output = ensure_demo_character(args.output, force=args.force)
    print(f"Demo character ready: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
