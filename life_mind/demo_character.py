"""Generate a neutral open-source demo sprite pack with no private character art."""

from __future__ import annotations

import json
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, ImageDraw


DEMO_IDENTITY = "life-mind-demo-seed"
CANVAS = (420, 400)
LOW_RES = (105, 100)
FRAME_COUNT = 12
CLIPS: dict[str, tuple[int, bool]] = {
    "idle": (90, True),
    "blink": (45, False),
    "draw": (80, True),
    "water": (75, True),
    "work": (80, True),
    "sleep": (110, True),
    "greet": (65, False),
    "happy": (65, False),
    "curious": (75, False),
    "surprised": (65, False),
    "pensive": (85, False),
    "relieved": (80, False),
    "look_around": (90, True),
    "hum": (85, True),
    "sit_down": (70, False),
    "stand_up": (70, False),
}


def _demo_is_complete(output: Path, payload: object) -> bool:
    if not isinstance(payload, dict) or payload.get("identity") != DEMO_IDENTITY:
        return False
    clips = payload.get("clips")
    if not isinstance(clips, dict) or set(clips) != set(CLIPS):
        return False
    return all(
        len(tuple((output / clip).glob("frame_*.png"))) == FRAME_COUNT
        for clip in CLIPS
    )


@contextmanager
def _generation_lock(output: Path):
    """Serialize first-run generation across two desktop-pet processes."""

    lock_path = output.with_name(output.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 90.0
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, str(os.getpid()).encode("ascii"))
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > 120.0
            except OSError:
                stale = False
            if stale:
                lock_path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"等待演示角色生成超时：{lock_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def _draw_demo_frame(clip: str, index: int) -> Image.Image:
    """Draw an intentionally simple seed-shaped mascot at low resolution."""

    phase = index / FRAME_COUNT
    wave = math.sin(phase * math.tau)
    one_shot = index / max(1, FRAME_COUNT - 1)
    bob = round(wave * 1.2)
    if clip == "happy":
        bob -= round(math.sin(one_shot * math.pi) * 5)
    elif clip == "surprised":
        bob -= round(math.sin(one_shot * math.pi) * 3)
    elif clip == "sleep":
        bob += 3
    elif clip == "sit_down":
        bob += round(one_shot * 5)
    elif clip == "stand_up":
        bob += round((1.0 - one_shot) * 5)

    image = Image.new("RGBA", LOW_RES, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    cx, cy = 52, 55 + bob

    # Shadow and feet.
    draw.ellipse((37, 83, 68, 88), fill=(56, 50, 48, 70))
    draw.rectangle((41, 78, 48, 84), fill=(76, 92, 67, 255))
    draw.rectangle((57, 78, 64, 84), fill=(76, 92, 67, 255))

    # A small non-human seed mascot: green shell, amber face and one leaf.
    draw.ellipse((35, cy - 24, 69, cy + 25), fill=(73, 123, 87, 255), outline=(40, 75, 55, 255), width=2)
    draw.ellipse((40, cy - 18, 64, cy + 10), fill=(246, 193, 83, 255), outline=(107, 76, 42, 255), width=2)
    draw.polygon(((50, cy - 25), (58, cy - 36), (61, cy - 24)), fill=(95, 151, 85, 255))

    look = 0
    if clip == "look_around":
        look = -2 if wave < -0.25 else 2 if wave > 0.25 else 0
    blink = clip == "blink" and 4 <= index <= 7
    if blink or clip == "relieved":
        draw.line((45, cy - 5, 49, cy - 5), fill=(74, 49, 35, 255), width=1)
        draw.line((56, cy - 5, 60, cy - 5), fill=(74, 49, 35, 255), width=1)
    else:
        draw.rectangle((46 + look, cy - 7, 48 + look, cy - 4), fill=(74, 49, 35, 255))
        draw.rectangle((57 + look, cy - 7, 59 + look, cy - 4), fill=(74, 49, 35, 255))
    if clip == "happy":
        draw.arc((48, cy - 2, 57, cy + 5), 0, 180, fill=(104, 55, 41, 255), width=1)
    elif clip == "surprised":
        draw.ellipse((51, cy, 54, cy + 4), outline=(104, 55, 41, 255))
    else:
        draw.line((50, cy + 2, 55, cy + 2), fill=(104, 55, 41, 255))

    # Clip-specific readable props. They are deliberately generic placeholders.
    if clip == "greet":
        arm_y = cy - 12 - round(math.sin(one_shot * math.pi * 3) * 4)
        draw.line((67, cy - 4, 78, arm_y), fill=(56, 99, 70, 255), width=3)
    elif clip == "curious":
        draw.text((72, cy - 22), "?", fill=(90, 65, 45, 255))
    elif clip == "surprised":
        draw.text((72, cy - 23), "!", fill=(190, 92, 61, 255))
    elif clip == "pensive":
        draw.ellipse((73, cy - 16, 75, cy - 14), fill=(90, 65, 45, 255))
        draw.ellipse((78, cy - 20, 80, cy - 18), fill=(90, 65, 45, 255))
    elif clip == "hum":
        draw.text((72, cy - 20), "♪", fill=(82, 91, 142, 255))
    elif clip == "sleep":
        draw.text((71, cy - 21), "Z", fill=(82, 91, 142, 255))
    elif clip == "water":
        draw.rectangle((69, cy + 4, 79, cy + 11), fill=(88, 139, 166, 255))
        draw.line((79, cy + 7, 87, cy + 3), fill=(88, 139, 166, 255), width=2)
        drop_y = cy + 9 + (index % 4) * 2
        draw.point((89, drop_y), fill=(77, 153, 207, 255))
    elif clip in {"draw", "work"}:
        draw.rectangle((28, cy + 18, 76, cy + 21), fill=(111, 78, 52, 255))
        prop_color = (244, 238, 218, 255) if clip == "draw" else (90, 111, 135, 255)
        draw.rectangle((45, cy + 10, 61, cy + 18), fill=prop_color, outline=(72, 61, 55, 255))

    return image.resize(CANVAS, Image.Resampling.NEAREST)


def ensure_demo_character(output: Path, *, force: bool = False) -> Path:
    """Create the public demo pack, refusing to overwrite an unrelated character."""

    output = Path(output)
    manifest_path = output / "manifest.json"
    with _generation_lock(output):
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            existing = {}
        if _demo_is_complete(output, existing) and not force:
            return output
        if existing and existing.get("identity") not in (None, DEMO_IDENTITY):
            raise ValueError(f"拒绝覆盖非演示角色目录：{output}")

        output.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, object] = {
            "format": 2,
            "style": "refined-pixel-art",
            "identity": DEMO_IDENTITY,
            "display_name": "小芽（演示）",
            "default_clip": "idle",
            "canvas": list(CANVAS),
            "anchor": {"head_x": 210, "baseline_y": 352},
            "clips": {},
        }
        for clip, (duration_ms, loop) in CLIPS.items():
            clip_dir = output / clip
            clip_dir.mkdir(parents=True, exist_ok=True)
            for old_frame in clip_dir.glob("frame_*.png"):
                old_frame.unlink()
            for index in range(FRAME_COUNT):
                _draw_demo_frame(clip, index).save(
                    clip_dir / f"frame_{index:03d}.png", optimize=True
                )
            manifest["clips"][clip] = {
                "duration_ms": duration_ms,
                "loop": loop,
                "frames": FRAME_COUNT,
            }
        # The manifest is the readiness marker and is intentionally written last.
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return output


__all__ = ("CANVAS", "CLIPS", "DEMO_IDENTITY", "FRAME_COUNT", "ensure_demo_character")
