"""Check relative links in Markdown files that are part of the public release."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

try:
    from tools.check_public_release import ROOT, _git_candidate_files, _intended_public_files
except ModuleNotFoundError:  # Direct execution adds tools/, not its parent, to sys.path.
    from check_public_release import ROOT, _git_candidate_files, _intended_public_files


LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:")


def public_markdown_files() -> list[Path]:
    candidates = _git_candidate_files()
    files = candidates if candidates is not None else _intended_public_files()
    return sorted(path for path in files if path.is_file() and path.suffix.casefold() == ".md")


def broken_links(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    for raw_target in LINK_PATTERN.findall(text):
        target = raw_target.strip().strip("<>")
        if not target or target.startswith("#") or target.casefold().startswith(EXTERNAL_PREFIXES):
            continue
        relative_target = unquote(target.split("#", 1)[0])
        if not relative_target:
            continue
        resolved = (path.parent / relative_target).resolve()
        try:
            resolved.relative_to(ROOT.resolve())
        except ValueError:
            errors.append(f"链接越出项目目录：{target}")
            continue
        if not resolved.exists():
            errors.append(f"目标不存在：{target}")
    return errors


def main() -> int:
    errors: list[str] = []
    files = public_markdown_files()
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        errors.extend(f"{relative}: {error}" for error in broken_links(path))

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"PASS: {len(files)} 个公开 Markdown 文件的本地链接均有效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
