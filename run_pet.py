"""Launch or validate the LIFE-Mind pixel desktop pet."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

LOCAL_DEPENDENCIES = Path(__file__).resolve().parent / ".deps" / "python"


def dependency_path_is_compatible(path: Path) -> bool:
    """Reject vendored native extensions built for another Python ABI."""

    if not path.is_dir():
        return False
    expected = f"cp{sys.version_info.major}{sys.version_info.minor}"
    tagged_extensions: set[str] = set()
    for extension in path.rglob("*.pyd"):
        match = re.search(r"\.(cp\d+)-", extension.name)
        if match:
            tagged_extensions.add(match.group(1))
    return not tagged_extensions or tagged_extensions == {expected}


if dependency_path_is_compatible(LOCAL_DEPENDENCIES) and str(LOCAL_DEPENDENCIES) not in sys.path:
    sys.path.insert(0, str(LOCAL_DEPENDENCIES))

from life_mind.apps.desktop_pet import (
    CONFIG_PATH,
    DEMO_ANIMATION_DIR,
    DEFAULT_ANIMATION_DIR,
    animation_report,
    run_desktop_pet,
)
from life_mind.demo_character import ensure_demo_character


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LIFE-Mind 多动作像素桌宠")
    parser.add_argument(
        "--asset",
        type=Path,
        default=DEFAULT_ANIMATION_DIR,
        help="精细像素动作库目录（必须包含当前角色 manifest.json）",
    )
    parser.add_argument("--check", action="store_true", help="只检查素材，不打开窗口")
    parser.add_argument("--reset-config", action="store_true", help="清除窗口位置与大小设置")
    parser.add_argument("--config-path", type=Path, default=CONFIG_PATH, help="窗口设置文件路径")
    parser.add_argument("--db-path", type=Path, help="心智数据库路径；留空使用用户本地数据库")
    parser.add_argument("--windowed", action="store_true", help="显示普通标题栏，供界面调试使用")
    parser.add_argument(
        "--developer-mode",
        action="store_true",
        help="显式开放内部状态与心智调试器；普通启动保持黑箱",
    )
    parser.add_argument(
        "--ui-qa-lightweight",
        action="store_true",
        help="界面验收时仅加载正式像素库的待机和眨眼动作",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    if args.reset_config and args.config_path.exists():
        args.config_path.unlink()

    asset = args.asset
    if asset.resolve() == DEMO_ANIMATION_DIR.resolve() and not (asset / "manifest.json").is_file():
        ensure_demo_character(asset)
    if args.check:
        print(json.dumps(animation_report(asset), ensure_ascii=True, indent=2))
        return 0

    run_desktop_pet(
        asset,
        config_path=args.config_path,
        mind_path=args.db_path,
        windowed=args.windowed,
        ui_qa_lightweight=args.ui_qa_lightweight,
        developer_mode=args.developer_mode,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
