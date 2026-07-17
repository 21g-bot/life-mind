"""Gently contract only the outer alpha fringe of rendered Puppet frames."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageFilter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--blend", type=float, default=0.65)
    args = parser.parse_args()
    blend = max(0.0, min(1.0, args.blend))
    files = sorted(args.directory.glob("frame_*.png"))
    if not files:
        raise SystemExit(f"No frames found in {args.directory}")
    for path in files:
        with Image.open(path) as source:
            image = source.convert("RGBA")
        alpha = image.getchannel("A")
        contracted = alpha.filter(ImageFilter.MinFilter(3))
        image.putalpha(Image.blend(alpha, contracted, blend))
        image.save(path, optimize=True)
    print(f"Refined {len(files)} alpha mattes in {args.directory}")


if __name__ == "__main__":
    main()
