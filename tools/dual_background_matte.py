"""Recover an alpha matte from aligned black- and white-background renders."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


def recover(black: Image.Image, white: Image.Image, contract: int = 1) -> Image.Image:
    b = np.asarray(black.convert("RGB"), dtype=np.float32) / 255.0
    w = np.asarray(white.convert("RGB"), dtype=np.float32) / 255.0
    if b.shape != w.shape:
        raise ValueError("Black and white renders must have identical dimensions")

    # For Cb = aF and Cw = aF + (1-a), every channel estimates 1-a.
    background_contribution = np.median(np.clip(w - b, 0.0, 1.0), axis=2)
    alpha = np.clip(1.0 - background_contribution, 0.0, 1.0)
    alpha[alpha < 2.0 / 255.0] = 0.0
    alpha[alpha > 253.0 / 255.0] = 1.0

    if contract > 0:
        matte = Image.fromarray(np.round(alpha * 255.0).astype(np.uint8), "L")
        size = contract * 2 + 1
        matte = matte.filter(ImageFilter.MinFilter(size=size))
        alpha = np.asarray(matte, dtype=np.float32) / 255.0

    safe = np.maximum(alpha[..., None], 1.0 / 255.0)
    foreground = np.clip(b / safe, 0.0, 1.0)
    output = np.dstack((foreground, alpha[..., None]))
    result = Image.fromarray(np.round(output * 255.0).astype(np.uint8), "RGBA")
    bbox = result.getchannel("A").getbbox()
    return result.crop(bbox) if bbox else result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("black", type=Path)
    parser.add_argument("white", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--content", default="11,45,1411,1445")
    parser.add_argument("--contract", type=int, default=1)
    args = parser.parse_args()

    crop = tuple(int(value) for value in args.content.split(","))
    if len(crop) != 4:
        raise ValueError("--content requires left,top,right,bottom")
    with Image.open(args.black) as image:
        black = image.convert("RGB").crop(crop)
    with Image.open(args.white) as image:
        white = image.convert("RGB").crop(crop)
    result = recover(black, white, args.contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.save(args.output, optimize=True)
    print(f"Recovered dual-background matte: {args.output} {result.size}")


if __name__ == "__main__":
    main()
