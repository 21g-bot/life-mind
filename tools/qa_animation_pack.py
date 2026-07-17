"""Measure and visualize spatial stability of a LIFE-Mind animation pack."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def head_anchor_x(frame: Image.Image, bbox: tuple[int, int, int, int]) -> float:
    array = np.asarray(frame.convert("RGBA"))
    left, top, right, bottom = bbox
    upper_bottom = min(bottom, top + round((bottom - top) * 0.48))
    region = array[top:upper_bottom, left:right]
    red, green, blue, alpha = [region[..., index] for index in range(4)]
    hair = (alpha > 80) & (red < 115) & (green < 90) & (blue < 82)
    _, xs = np.nonzero(hair)
    return left + float(np.median(xs)) if len(xs) >= 20 else (left + right) / 2


def frame_metrics(frame: Image.Image) -> dict[str, float]:
    bbox = frame.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("empty animation frame")
    left, top, right, bottom = bbox
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": right - left,
        "height": bottom - top,
        "center_x": (left + right) / 2,
        "head_anchor_x": head_anchor_x(frame, bbox),
    }


def temporal_delta(first: Image.Image, second: Image.Image) -> float:
    first_array = np.asarray(first.convert("RGBA"), dtype=np.int16)
    second_array = np.asarray(second.convert("RGBA"), dtype=np.int16)
    visible = (first_array[..., 3] > 24) | (second_array[..., 3] > 24)
    if not visible.any():
        return 0.0
    changed = (
        np.max(np.abs(first_array[..., :3] - second_array[..., :3]), axis=2) > 36
    ) | (np.abs(first_array[..., 3] - second_array[..., 3]) > 36)
    return float(changed[visible].mean())


def analyze(root: Path) -> dict[str, object]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    report: dict[str, object] = {"clips": {}}
    for name in manifest["clips"]:
        files = sorted((root / name).glob("frame_*.png"))
        frames = [Image.open(file).convert("RGBA") for file in files]
        metrics = [frame_metrics(frame) for frame in frames]
        centers = [item["center_x"] for item in metrics]
        head_anchors = [item["head_anchor_x"] for item in metrics]
        bottoms = [item["bottom"] for item in metrics]
        heights = [item["height"] for item in metrics]
        widths = [item["width"] for item in metrics]
        pairs = list(zip(frames, frames[1:]))
        pair_labels = [f"{index:03d}->{index + 1:03d}" for index in range(len(frames) - 1)]
        if manifest["clips"][name].get("loop", True) and len(frames) > 1:
            pairs.append((frames[-1], frames[0]))
            pair_labels.append(f"{len(frames) - 1:03d}->000")
        deltas = [temporal_delta(first, second) for first, second in pairs]
        maximum_delta_index = int(np.argmax(deltas)) if deltas else 0
        report["clips"][name] = {
            "frames": len(frames),
            "canvas": list(frames[0].size),
            "center_x_median": round(statistics.median(centers), 2),
            "center_x_jitter": round(max(centers) - min(centers), 2),
            "head_anchor_median": round(statistics.median(head_anchors), 2),
            "head_anchor_jitter": round(max(head_anchors) - min(head_anchors), 2),
            "baseline_median": round(statistics.median(bottoms), 2),
            "baseline_jitter": round(max(bottoms) - min(bottoms), 2),
            "height_median": round(statistics.median(heights), 2),
            "height_range": [min(heights), max(heights)],
            "width_median": round(statistics.median(widths), 2),
            "width_range": [min(widths), max(widths)],
            "temporal_delta_median": round(statistics.median(deltas), 4) if deltas else 0.0,
            "temporal_delta_max": round(max(deltas), 4) if deltas else 0.0,
            "temporal_delta_at": pair_labels[maximum_delta_index] if pair_labels else "",
            "loop_boundary_delta": round(deltas[-1], 4)
            if manifest["clips"][name].get("loop", True) and deltas else None,
            "frames_raw": metrics,
        }
    return report


def make_onion_sheet(root: Path, report: dict[str, object], output: Path) -> None:
    clips = report["clips"]
    first_name = next(iter(clips))
    width, height = clips[first_name]["canvas"]
    cell_width, cell_height = width // 2, height // 2
    names = list(clips)
    columns = 4
    rows = (len(names) + columns - 1) // columns
    sheet = Image.new("RGBA", (cell_width * columns, cell_height * rows), (255, 247, 222, 255))
    for index, name in enumerate(names):
        files = sorted((root / name).glob("frame_*.png"))
        overlay = Image.new("RGBA", (width, height), (255, 247, 222, 255))
        alpha_value = max(18, 160 // max(1, len(files)))
        for file in files:
            with Image.open(file) as source:
                frame = source.convert("RGBA")
            alpha = frame.getchannel("A").point(lambda value: round(value * alpha_value / 255))
            frame.putalpha(alpha)
            overlay.alpha_composite(frame)
        draw = ImageDraw.Draw(overlay)
        center = round(clips[name]["head_anchor_median"])
        baseline = round(clips[name]["baseline_median"])
        draw.line((center, 0, center, height), fill=(210, 55, 55, 190), width=1)
        draw.line((0, baseline, width, baseline), fill=(50, 110, 210, 190), width=1)
        thumb = overlay.resize((cell_width, cell_height), Image.Resampling.NEAREST)
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        sheet.alpha_composite(thumb, (x, y))
    sheet.save(output)


def strict_failures(
    report: dict[str, object],
    *,
    min_frames: int = 12,
    max_head_jitter: float = 3.0,
    max_baseline_jitter: float = 1.0,
    max_height_change: int = 32,
    max_temporal_delta: float = 0.50,
    max_transition_delta: float = 0.65,
) -> list[str]:
    failures: list[str] = []
    for name, metrics in report["clips"].items():
        if metrics["frames"] < min_frames:
            failures.append(f"{name}: fewer than {min_frames} frames")
        if metrics["head_anchor_jitter"] > max_head_jitter:
            failures.append(f"{name}: head anchor jitter {metrics['head_anchor_jitter']}px")
        if metrics["baseline_jitter"] > max_baseline_jitter:
            failures.append(f"{name}: baseline jitter {metrics['baseline_jitter']}px")
        low, high = metrics["height_range"]
        if name not in {"sit_down", "stand_up"} and high - low > max_height_change:
            failures.append(
                f"{name}: visible height changes by {high - low}px "
                f"({low}px to {high}px), exceeding {max_height_change}px"
            )
        temporal_limit = (
            max_transition_delta
            if name in {"sit_down", "stand_up"}
            else max_temporal_delta
        )
        if metrics["temporal_delta_max"] > temporal_limit:
            failures.append(
                f"{name}: temporal delta {metrics['temporal_delta_max']} "
                f"at {metrics['temporal_delta_at']} exceeds {temporal_limit}"
            )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--onion-sheet", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--min-frames", type=int, default=12)
    parser.add_argument("--max-head-jitter", type=float, default=3.0)
    parser.add_argument("--max-baseline-jitter", type=float, default=1.0)
    parser.add_argument("--max-height-change", type=int, default=32)
    parser.add_argument("--max-temporal-delta", type=float, default=0.50)
    parser.add_argument("--max-transition-delta", type=float, default=0.65)
    args = parser.parse_args()
    if args.min_frames < 1:
        parser.error("--min-frames must be at least 1")
    if min(
        args.max_head_jitter,
        args.max_baseline_jitter,
        args.max_height_change,
        args.max_temporal_delta,
        args.max_transition_delta,
    ) < 0:
        parser.error("strict QA limits cannot be negative")
    report = analyze(args.root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.onion_sheet:
        args.onion_sheet.parent.mkdir(parents=True, exist_ok=True)
        make_onion_sheet(args.root, report, args.onion_sheet)
    summary = {
        name: {
            key: value
            for key, value in metrics.items()
            if key in {
                "frames", "head_anchor_jitter", "center_x_jitter",
                "baseline_jitter", "height_range", "height_median",
                "temporal_delta_max", "temporal_delta_at",
            }
        }
        for name, metrics in report["clips"].items()
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.strict:
        failures = strict_failures(
            report,
            min_frames=args.min_frames,
            max_head_jitter=args.max_head_jitter,
            max_baseline_jitter=args.max_baseline_jitter,
            max_height_change=args.max_height_change,
            max_temporal_delta=args.max_temporal_delta,
            max_transition_delta=args.max_transition_delta,
        )
        if failures:
            raise SystemExit("strict animation QA failed:\n- " + "\n- ".join(failures))


if __name__ == "__main__":
    main()
