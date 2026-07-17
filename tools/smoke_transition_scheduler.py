"""Run the real Tk scheduler invisibly and verify a mid-loop activity change."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from life_mind.apps.desktop_pet import NativeDesktopPet


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()

    pet = NativeDesktopPet(args.root, config_path=Path("tmp/transition-smoke-config.json"))
    pet.root.withdraw()
    started = time.monotonic()
    events: list[dict[str, object]] = []
    request_snapshot: dict[str, object] = {}
    reaction_snapshot: dict[str, object] = {}
    original_set_clip = pet._set_clip

    def elapsed_ms() -> int:
        return round((time.monotonic() - started) * 1000)

    def traced_set_clip(name: str, *, return_after_ms: int | None = None) -> None:
        events.append({"at_ms": elapsed_ms(), "clip": name})
        original_set_clip(name, return_after_ms=return_after_ms)

    pet._set_clip = traced_set_clip  # type: ignore[method-assign]

    def start_watering() -> None:
        pet._begin_activity_transition("water")

    def request_drawing() -> None:
        request_snapshot["at_ms"] = elapsed_ms()
        request_snapshot["clip_before"] = pet.current_clip_name
        pet._transition_to_activity("draw")
        request_snapshot["pending_after"] = pet.pending_activity_name

    def request_surprise() -> None:
        reaction_snapshot["at_ms"] = elapsed_ms()
        reaction_snapshot["clip_before"] = pet.current_clip_name
        pet.react("!", duration_ms=2000, clip_name="surprised")

    pet.root.after(50, start_watering)
    pet.root.after(700, request_drawing)
    pet.root.after(7000, request_surprise)
    pet.root.after(18000, pet.root.quit)
    pet.root.mainloop()

    error = ""
    try:
        clips = [item["clip"] for item in events]
        if request_snapshot.get("clip_before") != "water":
            raise AssertionError(f"drawing request did not arrive during water: {request_snapshot}")
        if request_snapshot.get("pending_after") != "draw":
            raise AssertionError(f"drawing was not deferred to the loop boundary: {request_snapshot}")
        water_index = clips.index("water")
        sit_index = clips.index("sit_down")
        draw_index = clips.index("draw")
        if not water_index < sit_index < draw_index:
            raise AssertionError(f"unexpected clip order: {clips}")
        sit_event = events[sit_index]
        if int(sit_event["at_ms"]) - int(request_snapshot["at_ms"]) < 1400:
            raise AssertionError("water was interrupted before its authored loop boundary")
        first_phase_clips = [
            item["clip"] for item in events
            if int(item["at_ms"]) < int(reaction_snapshot["at_ms"])
        ]
        if "stand_up" in first_phase_clips:
            raise AssertionError("standing water-to-seated draw should not insert stand_up")
        if clips.count("__soft_transition__") < 3:
            raise AssertionError(f"missing single-sprite bridges: {clips}")
        reaction_events = [
            item for item in events if int(item["at_ms"]) >= int(reaction_snapshot["at_ms"])
        ]
        reaction_clips = [item["clip"] for item in reaction_events]
        required = ["stand_up", "surprised", "sit_down", "draw"]
        positions = [reaction_clips.index(name) for name in required]
        if positions != sorted(positions):
            raise AssertionError(f"seated reaction did not return through posture clips: {reaction_clips}")
    except (AssertionError, ValueError) as exc:
        error = str(exc)
    finally:
        report = {
            "ok": not error,
            "error": error,
            "request": request_snapshot,
            "reaction": reaction_snapshot,
            "events": events,
            "final_clip": pet.current_clip_name,
            "frame_job_active": bool(pet.frame_job),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        pet.mind.close()
        pet.root.destroy()
    if error:
        raise SystemExit(error)


if __name__ == "__main__":
    main()
