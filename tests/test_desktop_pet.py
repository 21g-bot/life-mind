from __future__ import annotations

import os
import subprocess
import sys
import unittest
import uuid
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from life_mind.ai import AIConfig, AIGeneration, LocalAIError, OllamaClient
from life_mind.behavior import BehaviorStateMachine, classify_dialogue_cue
from life_mind.apps.desktop_pet import (
    DEMO_ANIMATION_DIR,
    DEFAULT_ANIMATION_DIR,
    GifAnimation,
    NativeDesktopPet,
    PetConfig,
    RuntimePaths,
    SEATED_ACTIVITY_CLIPS,
    activity_transition_clips,
    animation_report,
    autonomy_tick_allowed,
    classify_user_text,
    load_animation_library,
    load_animation_manifest,
    make_soft_transition_frames,
    next_frame_cursor,
    resolved_clip_duration,
    resolve_runtime_paths,
)
from life_mind.demo_character import (
    CLIPS as DEMO_CLIPS,
    DEMO_IDENTITY,
    FRAME_COUNT as DEMO_FRAME_COUNT,
    ensure_demo_character,
    render_demo_icon,
)
from life_mind.apps.system_tray import SystemTrayController, make_tray_icon
from life_mind.mind import MindEngine
from run_pet import parse_args


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PixelAnimationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_demo_character(DEMO_ANIMATION_DIR)
        if DEFAULT_ANIMATION_DIR == DEMO_ANIMATION_DIR:
            ensure_demo_character(DEFAULT_ANIMATION_DIR)

    def test_internal_panels_require_explicit_developer_mode(self) -> None:
        self.assertFalse(parse_args([]).developer_mode)
        self.assertTrue(parse_args(["--developer-mode"]).developer_mode)
        self.assertTrue(parse_args(["--release-check"]).release_check)
        pet = object.__new__(NativeDesktopPet)
        pet.developer_mode = False
        with self.assertRaises(PermissionError):
            pet.open_mind_debugger()
        with self.assertRaises(PermissionError):
            pet.show_state()

    def test_launcher_check_works_with_the_active_python_abi(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", "run_pet.py", "--check"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            env={**os.environ, "PYTHONIOENCODING": "cp1252"},
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"style": "refined-pixel-art"', result.stdout)

    def test_frozen_runtime_uses_external_character_and_writable_demo_paths(self) -> None:
        source_root = PROJECT_ROOT / "synthetic-source"
        module_file = source_root / "life_mind" / "apps" / "desktop_pet.py"
        executable = PROJECT_ROOT / "synthetic-dist" / "LIFE-Mind.exe"
        config_dir = PROJECT_ROOT / "synthetic-profile" / "LIFE-Mind"

        source_paths = resolve_runtime_paths(
            frozen=False,
            module_file=module_file,
            executable=executable,
            config_dir=config_dir,
        )
        frozen_paths = resolve_runtime_paths(
            frozen=True,
            module_file=module_file,
            executable=executable,
            config_dir=config_dir,
        )

        self.assertIsInstance(frozen_paths, RuntimePaths)
        self.assertEqual(source_paths.root, source_root.resolve())
        self.assertEqual(
            source_paths.private_animation_dir,
            source_root.resolve() / "assets" / "character" / "pixel_pet_v2",
        )
        self.assertEqual(source_paths.demo_animation_dir, source_root.resolve() / ".cache" / "demo-character")
        self.assertEqual(frozen_paths.root, executable.resolve().parent)
        self.assertEqual(frozen_paths.private_animation_dir, executable.resolve().parent / "character")
        self.assertEqual(frozen_paths.demo_animation_dir, config_dir / "demo-character")

    def test_public_demo_icon_is_transparent_and_contains_the_seed_mascot(self) -> None:
        icon = render_demo_icon(256)
        self.assertEqual(icon.mode, "RGBA")
        self.assertEqual(icon.size, (256, 256))
        self.assertIsNotNone(icon.getchannel("A").getbbox())
        with self.assertRaises(ValueError):
            render_demo_icon(8)

    def test_soft_transition_never_overlays_two_sprites(self) -> None:
        image_module = __import__("PIL.Image", fromlist=["Image"])
        source = image_module.new("RGBA", (4, 2), (0, 0, 0, 0))
        target = image_module.new("RGBA", (4, 2), (0, 0, 0, 0))
        source.putpixel((0, 0), (255, 0, 0, 255))
        target.putpixel((3, 1), (0, 0, 255, 255))
        frames = make_soft_transition_frames(source, target)
        self.assertEqual(len(frames), 6)
        self.assertEqual(frames[0], source)
        self.assertEqual(frames[-1], target)
        for frame in frames[:3]:
            self.assertEqual(frame.getpixel((3, 1))[3], 0)
        for frame in frames[3:]:
            self.assertEqual(frame.getpixel((0, 0))[3], 0)

    def test_one_shot_animation_holds_its_last_frame(self) -> None:
        frame = __import__("PIL.Image", fromlist=["Image"]).new("RGBA", (2, 2))
        one_shot = GifAnimation((frame, frame), (100, 100), (2, 2), loop=False)
        looping = GifAnimation((frame, frame), (100, 100), (2, 2), loop=True)
        self.assertEqual(next_frame_cursor(one_shot, 1), 1)
        self.assertEqual(next_frame_cursor(looping, 1), 0)

    def test_sequence_duration_never_cuts_a_clip_short(self) -> None:
        frame = __import__("PIL.Image", fromlist=["Image"]).new("RGBA", (2, 2))
        animation = GifAnimation((frame, frame, frame), (40, 40, 40), (2, 2), loop=False)
        self.assertEqual(resolved_clip_duration(animation, 50), 120)
        self.assertEqual(resolved_clip_duration(animation, 300), 300)
        self.assertEqual(resolved_clip_duration(animation), 120)

    def test_pixel_animation_library_contract(self) -> None:
        clips, default_name = load_animation_library(DEFAULT_ANIMATION_DIR)
        manifest = load_animation_manifest(DEFAULT_ANIMATION_DIR)
        self.assertEqual(default_name, "idle")
        self.assertEqual(
            set(clips),
            {
                "idle", "blink", "happy", "curious", "draw", "water", "work", "sleep",
                "greet", "surprised", "pensive", "relieved", "look_around", "hum",
                "sit_down", "stand_up",
            },
        )
        self.assertEqual(len({clip.frame_count for clip in clips.values()}), 1)
        self.assertGreaterEqual(next(iter(clips.values())).frame_count, 8)
        self.assertEqual({clip.size for clip in clips.values()}, {(420, 400)})
        self.assertTrue(clips["idle"].loop)
        self.assertFalse(clips["happy"].loop)
        self.assertFalse(clips["sit_down"].loop)
        self.assertTrue(
            all(frame.mode == "RGBA" for clip in clips.values() for frame in clip.frames)
        )
        self.assertTrue(
            all(frame.getchannel("A").getbbox() for clip in clips.values() for frame in clip.frames)
        )
        report = animation_report(DEFAULT_ANIMATION_DIR)
        self.assertEqual(report["type"], "animation-library")
        self.assertEqual(report["style"], "refined-pixel-art")
        self.assertEqual(report["identity"], manifest["identity"])
        self.assertEqual(report["clips"], 16)
        self.assertEqual(report["frames"], sum(clip.frame_count for clip in clips.values()))

    def test_public_demo_uses_a_non_private_identity(self) -> None:
        report = animation_report(DEMO_ANIMATION_DIR)
        manifest = load_animation_manifest(DEMO_ANIMATION_DIR)
        self.assertEqual(report["identity"], DEMO_IDENTITY)
        self.assertEqual(report["display_name"], "小芽（演示）")
        self.assertEqual(manifest["display_name"], "小芽（演示）")
        self.assertEqual(report["clips"], 16)
        self.assertEqual(report["frames"], len(DEMO_CLIPS) * DEMO_FRAME_COUNT)

    def test_optional_identity_lock_rejects_the_wrong_character(self) -> None:
        with patch.dict(
            "os.environ", {"LIFE_MIND_CHARACTER_IDENTITY": "another-character"}
        ):
            with self.assertRaisesRegex(ValueError, "identity"):
                load_animation_manifest(DEMO_ANIMATION_DIR)
        with patch.dict(
            "os.environ", {"LIFE_MIND_CHARACTER_IDENTITY": DEMO_IDENTITY}
        ):
            self.assertEqual(
                load_animation_manifest(DEMO_ANIMATION_DIR)["identity"], DEMO_IDENTITY
            )

    def test_runtime_rejects_non_library_files(self) -> None:
        old_style_file = DEFAULT_ANIMATION_DIR / "idle" / "frame_000.png"
        with self.assertRaisesRegex(ValueError, "只接受像素动作库"):
            load_animation_library(old_style_file)

    def test_lightweight_qa_still_uses_the_formal_pixel_pack(self) -> None:
        clips, default_name = load_animation_library(
            DEFAULT_ANIMATION_DIR,
            clip_names={"idle", "blink"},
        )
        self.assertEqual(default_name, "idle")
        self.assertEqual(set(clips), {"idle", "blink"})
        self.assertGreaterEqual(sum(clip.frame_count for clip in clips.values()), 16)
        self.assertEqual({clip.size for clip in clips.values()}, {(420, 400)})

    def test_tray_icon_is_made_from_the_pixel_character(self) -> None:
        clips, _ = load_animation_library(DEFAULT_ANIMATION_DIR, clip_names={"idle"})
        icon = make_tray_icon(clips["idle"].frames[0])
        self.assertEqual(icon.size, (64, 64))
        self.assertEqual(icon.mode, "RGBA")
        self.assertIsNotNone(icon.getchannel("A").getbbox())

    def test_tray_default_action_dispatches_visibility_restore(self) -> None:
        class FakeRoot:
            def after(self, _delay, callback):
                callback()

        class FakeItem:
            def __init__(self, text, action, **options):
                self.text = text
                self.action = action
                self.options = options

        class FakeMenu:
            SEPARATOR = object()

            def __init__(self, *items):
                self.items = items

        class FakeIcon:
            def __init__(self, name, image, title, menu):
                self.name = name
                self.image = image
                self.title = title
                self.menu = menu
                self.detached = False
                self.stopped = False

            def run_detached(self):
                self.detached = True

            def update_menu(self):
                return None

            def stop(self):
                self.stopped = True

        class FakeBackend:
            Menu = FakeMenu
            MenuItem = FakeItem
            Icon = FakeIcon

        source = __import__("PIL.Image", fromlist=["Image"]).new(
            "RGBA", (8, 8), (255, 180, 0, 255)
        )
        calls: list[str] = []
        controller = SystemTrayController(
            FakeRoot(),
            source,
            is_hidden=lambda: True,
            toggle_visibility=lambda: calls.append("visibility"),
            is_do_not_disturb=lambda: False,
            toggle_do_not_disturb=lambda: calls.append("dnd"),
            is_paused=lambda: False,
            toggle_pause=lambda: calls.append("pause"),
            close_application=lambda: calls.append("close"),
            character_name="小芽（演示）",
            backend=FakeBackend,
        )
        self.assertTrue(controller.start())
        self.assertTrue(controller.icon.detached)
        self.assertEqual(controller.icon.title, "LIFE-Mind · 小芽（演示）")
        visibility_item = controller.icon.menu.items[0]
        self.assertTrue(visibility_item.options["default"])
        visibility_item.action(controller.icon, visibility_item)
        self.assertEqual(calls, ["visibility"])
        controller.stop()

    def test_launcher_has_no_legacy_gif_option(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["--gif", "old-wallpaper.gif"])


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(__file__).with_name(
            f"desktop-pet-test-config-{uuid.uuid4().hex}.json"
        )

    def tearDown(self) -> None:
        self.path.unlink(missing_ok=True)
        self.path.with_suffix(".tmp").unlink(missing_ok=True)

    def test_round_trip(self) -> None:
        expected = PetConfig(
            x=120,
            y=240,
            scale=2,
            topmost=False,
            swaying=False,
            do_not_disturb=True,
        )
        expected.save(self.path)
        self.assertEqual(PetConfig.load(self.path), expected)

    def test_invalid_scale_falls_back(self) -> None:
        self.path.write_text('{"scale": 99}', encoding="utf-8")
        self.assertEqual(PetConfig.load(self.path).scale, 2)

    def test_valid_json_with_wrong_shape_falls_back(self) -> None:
        self.path.write_text('["not", "an", "object"]', encoding="utf-8")
        self.assertEqual(PetConfig.load(self.path), PetConfig())

    def test_config_values_are_parsed_without_truthy_string_or_bool_int_leaks(self) -> None:
        self.path.write_text(
            '{"x": true, "y": 240, "scale": true, "topmost": "false", '
            '"swaying": "yes", "do_not_disturb": "invalid"}',
            encoding="utf-8",
        )
        self.assertEqual(
            PetConfig.load(self.path),
            PetConfig(
                x=None,
                y=240,
                scale=2,
                topmost=False,
                swaying=True,
                do_not_disturb=False,
            ),
        )


class ReactionTests(unittest.TestCase):
    def test_do_not_disturb_blocks_only_unsolicited_autonomy(self) -> None:
        self.assertFalse(
            autonomy_tick_allowed(
                do_not_disturb=True,
                dragging=False,
                paused=False,
                reacting=False,
                sequencing=False,
            )
        )
        self.assertTrue(
            autonomy_tick_allowed(
                do_not_disturb=False,
                dragging=False,
                paused=False,
                reacting=False,
                sequencing=False,
            )
        )

    def test_activity_transitions_only_change_physical_posture(self) -> None:
        self.assertEqual(activity_transition_clips("idle", "draw"), ("sit_down",))
        self.assertEqual(activity_transition_clips("sleep", "water"), ("stand_up",))
        self.assertEqual(activity_transition_clips("draw", "sleep"), ())
        self.assertEqual(activity_transition_clips("idle", "water"), ())

    def test_watering_is_a_standing_activity(self) -> None:
        self.assertNotIn("water", SEATED_ACTIVITY_CLIPS)
        self.assertEqual(SEATED_ACTIVITY_CLIPS, {"draw", "work", "sleep"})

    def test_text_reactions(self) -> None:
        self.assertEqual(classify_user_text("为什么呀？")[0], "?")
        self.assertEqual(classify_user_text("真的太震惊了！")[0], "!")
        self.assertEqual(classify_user_text("你好可爱")[0], "♪")
        self.assertEqual(classify_user_text("这个不对")[0], "…")

    def test_dialogue_cues_have_explainable_affect(self) -> None:
        praise = classify_dialogue_cue("谢谢，你真的很可爱")
        self.assertEqual(praise.emotion, "happy")
        self.assertGreater(praise.mood_delta, 0)
        self.assertIn("肯定", praise.reason)
        correction = classify_dialogue_cue("不对，需要重新改")
        self.assertEqual(correction.emotion, "pensive")
        self.assertGreater(correction.trust_delta, -0.01)

    def test_idle_state_machine_obeys_energy_and_cooldowns(self) -> None:
        class LowEnergyState:
            energy = 0.18
            mood = 0.62
            trust = 0.55

        machine = BehaviorStateMachine(seed=7, now=0.0)
        machine.cooldowns.update({"idle": 100.0, "draw": 100.0})
        decision = machine.tick(LowEnergyState(), now=20.0)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.activity, "sleep")
        self.assertIn("精力", decision.reason)

    def test_state_machine_does_not_interrupt_recent_dialogue(self) -> None:
        class NormalState:
            energy = 0.72
            mood = 0.66
            trust = 0.55

        machine = BehaviorStateMachine(seed=2, now=0.0)
        machine.on_dialogue("你好", "♪", NormalState(), now=10.0)
        self.assertIsNone(machine.tick(NormalState(), now=20.0))

    def test_autonomy_candidates_follow_mood_bands(self) -> None:
        class HappyState:
            energy = 0.82
            mood = 0.91
            trust = 0.70

        class LowMoodState:
            energy = 0.68
            mood = 0.22
            trust = 0.48

        self.assertNotIn("sleep", dict(BehaviorStateMachine._candidate_weights(HappyState())))
        self.assertIn("hum", dict(BehaviorStateMachine._candidate_weights(HappyState())))
        self.assertNotIn("hum", dict(BehaviorStateMachine._candidate_weights(LowMoodState())))
        self.assertGreater(dict(BehaviorStateMachine._candidate_weights(LowMoodState()))["draw"], 1.0)


class FakeAI:
    def generate(self, messages, *, allow_reflection: bool) -> AIGeneration:
        prompt = "\n".join(item["content"] for item in messages)
        reply = "我会根据本地记忆自然地回应你。"
        if "用户希望被称为“小林”" in prompt:
            reply = "小林，我记得这个称呼。"
        return AIGeneration(
            reply=reply,
            symbol="♪",
            reflection="我可以在没有任务时安静陪伴。" if allow_reflection else "",
            memories=({"content": "用户喜欢安静的音乐", "category": "preference", "confidence": 0.72},),
            model="fake-local-model",
        )


class BrokenAI:
    def generate(self, messages, *, allow_reflection: bool) -> AIGeneration:
        raise LocalAIError("测试中的模型未启动")


class HallucinatingAI:
    def generate(self, messages, *, allow_reflection: bool) -> AIGeneration:
        return AIGeneration("我上次画过一张风景草图。", "♪", model="fake-local-model")


class MindTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(__file__).with_name(f"life-mind-test-{uuid.uuid4().hex}.db")

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)

    def test_memory_survives_restart_and_can_be_deleted(self) -> None:
        engine = MindEngine(self.path)
        engine.process_user_text("我叫小林。")
        engine.process_user_text("我喜欢安静的音乐。")
        memory_id = next(item.id for item in engine.memories() if item.memory_key == "user.name")
        engine.close()

        reopened = MindEngine(self.path)
        self.assertIn("小林", reopened.process_user_text("我叫什么？").text)
        self.assertIn("安静的音乐", reopened.process_user_text("我喜欢什么？").text)
        reopened.delete_memory(memory_id)
        reopened.close()

        final = MindEngine(self.path)
        self.assertFalse(any(item.id == memory_id for item in final.memories()))
        self.assertGreaterEqual(final.state().interaction_count, 4)
        final.close()

    def test_character_name_is_runtime_configuration(self) -> None:
        engine = MindEngine(self.path, character_name="小芽")
        self.assertIn("你是桌宠小芽", engine._system_prompt())
        engine.close()

    def test_ai_reply_uses_local_memory_and_marks_source(self) -> None:
        engine = MindEngine(self.path, ai_responder=FakeAI())
        engine.process_user_text("我叫小林。")
        response = engine.process_user_text("我偏爱安静的音乐。")
        self.assertTrue(response.ai_generated)
        self.assertIn("小林", response.text)
        self.assertIn("fake-local-model", response.ai_status)
        self.assertTrue(any(item.source == "ai_interpretation" for item in engine.memories()))
        engine.close()

    def test_ai_failure_falls_back_without_losing_memory(self) -> None:
        engine = MindEngine(self.path, ai_responder=BrokenAI())
        response = engine.process_user_text("请记住：周五整理照片。")
        self.assertFalse(response.ai_generated)
        self.assertIn("记住", response.text)
        self.assertTrue(engine.memories())
        engine.close()

    def test_unsupported_ai_activity_claim_is_grounded(self) -> None:
        engine = MindEngine(self.path, ai_responder=HallucinatingAI())
        response = engine.process_user_text("我喜欢安静的音乐。")
        self.assertNotIn("画过", response.text)
        self.assertIn("没有真的做过", response.text)
        engine.close()

    def test_mood_cause_and_activity_effect_are_persistent(self) -> None:
        engine = MindEngine(self.path)
        engine.process_user_text("谢谢，你很可爱")
        praised = engine.state()
        self.assertEqual(praised.dominant_emotion, "happy")
        self.assertIn("肯定", praised.emotion_cause)
        before_energy = praised.energy
        engine.apply_activity_effect("sleep", "精力偏低，选择休息")
        rested = engine.state()
        self.assertGreater(rested.energy, before_energy)
        self.assertEqual(rested.dominant_emotion, "tired")
        engine.close()


class AIConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(__file__).with_name(
            f"ai-test-config-{uuid.uuid4().hex}.json"
        )

    def tearDown(self) -> None:
        self.path.unlink(missing_ok=True)
        self.path.with_suffix(".tmp").unlink(missing_ok=True)

    def test_config_round_trip(self) -> None:
        expected = AIConfig(False, "http://127.0.0.1:9999", "qwen-test", 12.0)
        expected.save(self.path)
        self.assertEqual(AIConfig.load(self.path), expected)

    def test_disabled_client_does_not_touch_network(self) -> None:
        ok, detail = OllamaClient(AIConfig(enabled=False)).status()
        self.assertFalse(ok)
        self.assertIn("关闭", detail)


if __name__ == "__main__":
    unittest.main()
