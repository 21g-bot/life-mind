"""Build a private-data-free LIFE-Mind portable ZIP on Windows."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from life_mind import __version__
from life_mind.demo_character import render_demo_icon


PRODUCT_NAME = "LIFE-Mind"
ARTIFACT_STEM = f"{PRODUCT_NAME}-v{__version__}-windows-x64"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_zip(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, (Path(source.name) / path.relative_to(source)).as_posix())


def main() -> int:
    if os.name != "nt":
        print("ERROR: PyInstaller Windows 发行包必须在 Windows 上构建。")
        return 2

    build_root = ROOT / "build" / "release"
    dist_root = ROOT / "dist" / "windows"
    release_root = ROOT / "dist" / "release"
    build_root.mkdir(parents=True, exist_ok=True)
    dist_root.mkdir(parents=True, exist_ok=True)
    release_root.mkdir(parents=True, exist_ok=True)

    icon_path = build_root / f"{PRODUCT_NAME}.ico"
    render_demo_icon().save(
        icon_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_root),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        str(ROOT / "packaging" / "LIFE-Mind.spec"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)

    bundle = dist_root / PRODUCT_NAME
    executable = bundle / f"{PRODUCT_NAME}.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"PyInstaller 未生成预期文件：{executable}")
    for filename in ("LICENSE", "NOTICE", "README.md"):
        shutil.copy2(ROOT / filename, bundle / filename)

    zip_path = release_root / f"{ARTIFACT_STEM}.zip"
    checksum_path = release_root / f"{ARTIFACT_STEM}.sha256"
    _write_zip(bundle, zip_path)
    checksum_path.write_text(f"{_sha256(zip_path)}  {zip_path.name}\n", encoding="ascii")

    from tools.verify_windows_release import validate_windows_release

    errors = validate_windows_release(zip_path, checksum_path)
    if errors:
        raise RuntimeError("发行包自检失败：\n- " + "\n- ".join(errors))
    print(zip_path)
    print(checksum_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
