"""Render representative runtime soft transitions on a warm desktop matte."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from life_mind.apps.desktop_pet import make_soft_transition_frames


ROUTES = (
    ("idle", "water"),
    ("water", "sit_down"),
    ("sit_down", "draw"),
    ("sleep", "stand_up"),
    ("stand_up", "surprised"),
)


def endpoint(root: Path, clip: str, *, first: bool) -> Image.Image:
    files = sorted((root / clip).glob("frame_*.png"))
    return Image.open(files[0 if first else -1]).convert("RGBA")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    thumb_size = (168, 160)
    row_height = 186
    sheet = Image.new("RGB", (thumb_size[0] * 6, row_height * len(ROUTES)), (255, 247, 222))
    draw = ImageDraw.Draw(sheet)
    for row, (source_name, target_name) in enumerate(ROUTES):
        source = endpoint(args.root, source_name, first=False)
        target = endpoint(args.root, target_name, first=True)
        frames = make_soft_transition_frames(source, target)
        for column, frame in enumerate(frames):
            matte = Image.new("RGB", frame.size, (255, 247, 222))
            matte.paste(frame.convert("RGB"), mask=frame.getchannel("A"))
            sheet.paste(
                matte.resize(thumb_size, Image.Resampling.NEAREST),
                (column * thumb_size[0], row * row_height),
            )
        draw.rectangle((0, row * row_height + 160, sheet.width, row * row_height + 185), fill=(74, 54, 40))
        draw.text(
            (8, row * row_height + 166),
            f"{source_name} -> {target_name}",
            fill=(255, 247, 222),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
