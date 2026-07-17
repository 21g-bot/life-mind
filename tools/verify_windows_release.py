"""Validate the portable Windows ZIP before it can become a GitHub Release."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


REQUIRED_MEMBERS = {
    "LIFE-Mind/LIFE-Mind.exe",
    "LIFE-Mind/LICENSE",
    "LIFE-Mind/NOTICE",
    "LIFE-Mind/README.md",
}
FORBIDDEN_PARTS = {
    ".cache",
    ".deps",
    ".env",
    "assets",
    "character",
    "data",
    "source",
    "tmp",
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".db-shm",
    ".db-wal",
    ".sqlite",
    ".sqlite3",
}
CHECKSUM_PATTERN = re.compile(r"^(?P<digest>[0-9a-f]{64})  (?P<name>[^\r\n]+)\s*$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_windows_release(zip_path: Path, checksum_path: Path) -> list[str]:
    """Return every release-boundary error without extracting the archive."""

    zip_path = Path(zip_path)
    checksum_path = Path(checksum_path)
    errors: list[str] = []
    if not zip_path.is_file():
        return [f"找不到发行包：{zip_path}"]
    if not checksum_path.is_file():
        return [f"找不到校验文件：{checksum_path}"]

    match = CHECKSUM_PATTERN.fullmatch(checksum_path.read_text(encoding="ascii"))
    if match is None:
        errors.append("SHA256 文件格式无效")
    else:
        if match.group("name") != zip_path.name:
            errors.append("SHA256 文件记录的文件名与 ZIP 不一致")
        if match.group("digest") != sha256_file(zip_path):
            errors.append("SHA256 校验值与 ZIP 内容不一致")

    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = set(archive.namelist())
            missing = REQUIRED_MEMBERS.difference(members)
            for member in sorted(missing):
                errors.append(f"发行包缺少：{member}")
            for member in sorted(members):
                path = PurePosixPath(member)
                if path.is_absolute() or ".." in path.parts or "\\" in member:
                    errors.append(f"发行包含不安全路径：{member}")
                    continue
                lowered_parts = {part.casefold() for part in path.parts}
                if lowered_parts.intersection(FORBIDDEN_PARTS):
                    errors.append(f"发行包含私人或本地目录：{member}")
                lowered = member.casefold()
                if any(lowered.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
                    errors.append(f"发行包含运行数据库：{member}")
            executable = archive.read("LIFE-Mind/LIFE-Mind.exe") if not missing else b""
            if executable[:2] != b"MZ":
                errors.append("LIFE-Mind.exe 不是有效的 Windows PE 文件")
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        errors.append(f"发行包无法读取：{error}")
    return errors


def smoke_test_executable(zip_path: Path, timeout_seconds: int = 120) -> None:
    """Run the frozen launcher's non-interactive asset check in an isolated profile."""

    if os.name != "nt":
        raise RuntimeError("冻结版运行检查只能在 Windows 上执行")
    with tempfile.TemporaryDirectory(prefix="life-mind-release-") as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(root)
        executable = root / "LIFE-Mind" / "LIFE-Mind.exe"
        environment = {**os.environ, "LOCALAPPDATA": str(root / "profile")}
        result = subprocess.run(
            [str(executable), "--release-check"],
            env=environment,
            timeout=timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"冻结版 --release-check 失败，退出码 {result.returncode}")
        manifest = root / "profile" / "LIFE-Mind" / "demo-character" / "manifest.json"
        if not manifest.is_file():
            raise RuntimeError("冻结版没有在隔离的用户目录生成公开演示角色")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查 LIFE-Mind Windows 便携发行包")
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("checksum_path", type=Path)
    parser.add_argument("--run", action="store_true", help="在 Windows 隔离目录运行 EXE --check")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors = validate_windows_release(args.zip_path, args.checksum_path)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    if args.run:
        try:
            smoke_test_executable(args.zip_path)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            print(f"ERROR: {error}")
            return 1
    print(f"PASS: Windows 发行包边界、PE 文件与 SHA256 校验通过：{args.zip_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
