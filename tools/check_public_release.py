"""Fail fast when an intended public release includes private or local-only files."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIRS = (
    "life_mind",
    "tests",
    "tools",
    "docs",
    "examples",
    "schemas",
    "simulations",
    "packaging",
    ".github",
)
PUBLIC_ROOT_FILES = {
    ".gitignore",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "NOTICE",
    "README.md",
    "SECURITY.md",
    "pyproject.toml",
    "requirements-dev.txt",
    "requirements-build.txt",
    "requirements.txt",
    "run_pet.py",
    "start_pet.bat",
}
ALLOWED_CHARACTER_FILE = "assets/character/README.md"
FORBIDDEN_PREFIXES = (
    ".cache/",
    ".deps/",
    ".venv/",
    "assets/character/",
    "blind-responses/",
    "data/",
    "source/",
    "tmp/",
    "tools/archive_wallpaper_pipeline/",
)
FORBIDDEN_EXACT = {
    "docs/CHARACTER_SEED.md",
    "docs/VISUAL_DIRECTION.md",
    "simulations/mvp_growth.json",
    "tools/build_pixel_animation_pack.py",
    "tools/stabilize_animation_pack.py",
}
FORBIDDEN_SUFFIXES = (
    ".db",
    ".db-shm",
    ".db-wal",
    ".env",
    ".pyd",
    ".pyc",
    ".sqlite",
    ".sqlite3",
)
REQUIRED_IGNORE_LINES = {
    ".cache/",
    ".deps/",
    ".venv/",
    "/assets/character/*",
    "/data/",
    "/docs/CHARACTER_SEED.md",
    "/docs/VISUAL_DIRECTION.md",
    "/simulations/mvp_growth.json",
    "/source/",
    "/tmp/",
    "*.db",
    "*.db-shm",
    "*.db-wal",
    ".env",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "common API token": re.compile(
        r"(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{16,}|AKIA[0-9A-Z]{16})"
    ),
    "WeChat identifier": re.compile(r"\bwxid_[A-Za-z0-9_]{6,}\b", re.I),
    "Windows user directory": re.compile(r"\b[A-Z]:\\Users\\[^\\\s]+", re.I),
    "local development path": re.compile(r"\b[A-Z]:\\(?:codex|workspace|projects?)\\", re.I),
}
PRIVATE_IDENTITY_PATTERNS = {
    "private character name": re.compile(r"\b" + "Lu" + r"mi\b|" + "露" + "米", re.I),
    "private character motif": re.compile("sun" + "flower|" + "向" + "日葵", re.I),
    "private character identity": re.compile("sun" + "flower-girl", re.I),
    "private visual anchor": re.compile(
        "identity-reference-" + "original|character-pixel-" + "anchor", re.I
    ),
}
REQUIRED_PUBLIC_FILES = {"LICENSE", "NOTICE", "README.md", "SECURITY.md"}
TEXT_LIMIT = 2 * 1024 * 1024
MAX_PUBLIC_FILE_SIZE = 10 * 1024 * 1024


def _git_candidate_files() -> list[Path] | None:
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return None
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def _intended_public_files() -> list[Path]:
    files = [ROOT / name for name in PUBLIC_ROOT_FILES if (ROOT / name).is_file()]
    character_readme = ROOT / ALLOWED_CHARACTER_FILE
    if character_readme.is_file():
        files.append(character_readme)
    for directory in PUBLIC_DIRS:
        root = ROOT / directory
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT).as_posix()
            if _is_forbidden(relative):
                continue
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return sorted(set(files))


def _is_forbidden(relative: str) -> bool:
    if relative == ALLOWED_CHARACTER_FILE:
        return False
    lowered = relative.casefold()
    if lowered in {item.casefold() for item in FORBIDDEN_EXACT}:
        return True
    if any(lowered.startswith(prefix.casefold()) for prefix in FORBIDDEN_PREFIXES):
        return True
    return any(lowered.endswith(suffix.casefold()) for suffix in FORBIDDEN_SUFFIXES)


def _private_identity_hits(text: str) -> list[str]:
    return [label for label, pattern in PRIVATE_IDENTITY_PATTERNS.items() if pattern.search(text)]


def main() -> int:
    errors: list[str] = []
    for required in sorted(REQUIRED_PUBLIC_FILES):
        if not (ROOT / required).is_file():
            errors.append(f"缺少公开仓库必需文件：{required}")

    license_path = ROOT / "LICENSE"
    if license_path.is_file():
        license_text = license_path.read_text(encoding="utf-8")
        if "Apache License" not in license_text or "Version 2.0, January 2004" not in license_text:
            errors.append("LICENSE 不是完整可识别的 Apache License 2.0 文本")

    notice_path = ROOT / "NOTICE"
    if notice_path.is_file():
        notice_text = notice_path.read_text(encoding="utf-8")
        if "21g-bot" not in notice_text or "Copyright 2026" not in notice_text:
            errors.append("NOTICE 缺少维护者署名或版权年份")

    ignore_path = ROOT / ".gitignore"
    ignore_lines = {
        line.strip()
        for line in ignore_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    for required in sorted(REQUIRED_IGNORE_LINES.difference(ignore_lines)):
        errors.append(f".gitignore 缺少：{required}")

    candidates = _git_candidate_files()
    mode = "Git 首次提交候选文件" if candidates is not None else "预期公开文件"
    files = candidates if candidates is not None else _intended_public_files()
    total_size = 0
    for path in files:
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if _is_forbidden(relative):
            errors.append(f"禁止公开的文件：{relative}")
            continue
        size = path.stat().st_size
        total_size += size
        if size > MAX_PUBLIC_FILE_SIZE:
            errors.append(f"公开文件超过 10 MB：{relative} ({size / 1024 / 1024:.1f} MB)")
        if size > TEXT_LIMIT:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"疑似 {label}：{relative}")
        for label in _private_identity_hits(text):
            errors.append(f"疑似 {label}：{relative}")

    print(f"检查范围：{mode}，{len(files)} 个文件，约 {total_size / 1024 / 1024:.2f} MB")
    if errors:
        for error in sorted(set(errors)):
            print(f"ERROR: {error}")
        return 1
    print(
        "PASS: 许可证与署名完整，未发现数据库、私人素材、私人角色身份、缓存、"
        "常见密钥形态或本机绝对路径。"
    )
    if candidates is None:
        print("提示：当前还不是 Git 仓库；git init 和 git add 后请再运行一次检查已跟踪文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
