"""Audit every LIFE-Mind clip boundary and render the riskiest transitions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from qa_animation_pack import frame_metrics, temporal_delta


def load_endpoints(root: Path) -> dict[str, tuple[Image.Image, Image.Image]]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    endpoints: dict[str, tuple[Image.Image, Image.Image]] = {}
    for name in manifest["clips"]:
        files = sorted((root / name).glob("frame_*.png"))
        if not files:
            raise ValueError(f"{name}: no animation frames")
        endpoints[name] = (
            Image.open(files[0]).convert("RGBA"),
            Image.open(files[-1]).convert("RGBA"),
        )
    return endpoints


def analyze(root: Path) -> dict[str, object]:
    endpoints = load_endpoints(root)
    transitions: list[dict[str, object]] = []
    for source, (_, source_last) in endpoints.items():
        source_metrics = frame_metrics(source_last)
        for target, (target_first, _) in endpoints.items():
            if source == target:
                continue
            target_metrics = frame_metrics(target_first)
            transitions.append(
                {
                    "source": source,
                    "target": target,
                    "delta": round(temporal_delta(source_last, target_first), 4),
                    "head_shift": round(
                        abs(source_metrics["head_anchor_x"] - target_metrics["head_anchor_x"]), 2
                    ),
                    "baseline_shift": round(abs(source_metrics["bottom"] - target_metrics["bottom"]), 2),
                    "height_shift": round(abs(source_metrics["height"] - target_metrics["height"]), 2),
                }
            )
    transitions.sort(key=lambda item: (item["delta"], item["height_shift"]), reverse=True)
    return {"root": str(root.resolve()), "transitions": transitions}


def render_sheet(root: Path, report: dict[str, object], output: Path, limit: int) -> None:
    endpoints = load_endpoints(root)
    rows = min(limit, len(report["transitions"]))
    thumb_size = (210, 200)
    row_height = 226
    sheet = Image.new("RGB", (thumb_size[0] * 2, rows * row_height), (255, 247, 222))
    draw = ImageDraw.Draw(sheet)
    for row, item in enumerate(report["transitions"][:rows]):
        source_last = endpoints[item["source"]][1]
        target_first = endpoints[item["target"]][0]
        for column, frame in enumerate((source_last, target_first)):
            matte = Image.new("RGB", frame.size, (255, 247, 222))
            matte.paste(frame.convert("RGB"), mask=frame.getchannel("A"))
            thumb = matte.resize(thumb_size, Image.Resampling.NEAREST)
            sheet.paste(thumb, (column * thumb_size[0], row * row_height))
        label = (
            f"{item['source']} -> {item['target']}  delta={item['delta']}  "
            f"head={item['head_shift']}  height={item['height_shift']}"
        )
        draw.rectangle((0, row * row_height + 200, 420, row * row_height + 225), fill=(74, 54, 40))
        draw.text((8, row * row_height + 205), label, fill=(255, 247, 222))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=24)
    args = parser.parse_args()
    report = analyze(args.root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    render_sheet(args.root, report, args.sheet, args.limit)
    print(json.dumps(report["transitions"][: args.limit], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
