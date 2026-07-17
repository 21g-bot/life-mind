"""Validate a public LIFE-Mind interchange contract.

This utility intentionally has no third-party dependencies.  JSON Schema
files are published for other languages; the reference host uses the same
rules implemented in :mod:`life_mind.contracts`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from life_mind.contracts import CONTRACT_TYPES, load_contract


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验 LIFE-Mind Life Package、Capability Manifest 或 Experience Protocol。"
    )
    parser.add_argument("kind", choices=sorted(CONTRACT_TYPES), help="协议类型")
    parser.add_argument("paths", nargs="+", type=Path, help="一个或多个 JSON 文件")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    failed = False
    for path in args.paths:
        try:
            contract = load_contract(args.kind, path)
        except (OSError, ValueError, TypeError) as exc:
            failed = True
            print(f"ERROR {args.kind} {path}: {exc}", file=sys.stderr)
        else:
            print(
                f"OK {args.kind} {path}: "
                f"schemaVersion={contract.schema_version}"
            )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
