from __future__ import annotations

import unittest
import uuid
from pathlib import Path

from life_mind.mind import MindEngine


class PersistentMindIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(__file__).with_name(
            f"life-mind-integration-test-{uuid.uuid4().hex}.db"
        )

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)

    def test_live_task_request_is_one_event_and_drives_work_clip(self) -> None:
        engine = MindEngine(self.path)

        response = engine.process_user_text("帮我完成这个任务")
        snapshot = engine.debug_snapshot()

        self.assertEqual(snapshot["event_count"], 1)
        self.assertEqual(snapshot["last_trace"]["event"]["event_type"], "task_request")
        self.assertEqual(response.mind_action, "accept_task")
        self.assertEqual(response.mind_clip, "work")
        engine.close()

    def test_runtime_state_and_last_decision_survive_restart_by_replay(self) -> None:
        engine = MindEngine(self.path)
        engine.process_user_text("帮我完成这个任务")
        engine.apply_activity_effect("water", "照料桌边的小植物")
        before = engine.debug_snapshot()
        before_decision = engine.last_mind_decision()
        engine.close()

        reopened = MindEngine(self.path)
        after = reopened.debug_snapshot()

        self.assertEqual(after["event_count"], before["event_count"])
        self.assertEqual(after["state"], before["state"])
        self.assertEqual(reopened.last_mind_decision(), before_decision)
        self.assertFalse(after["replay_errors"])
        reopened.close()

    def test_autonomous_activity_is_arbitrated_before_selecting_animation(self) -> None:
        engine = MindEngine(self.path)

        engine.apply_activity_effect("water", "照料桌边的小植物")
        decision = engine.last_mind_decision()

        self.assertEqual(decision["action"], "care_for_plant")
        self.assertEqual(decision["clip"], "water")
        self.assertEqual(engine.debug_snapshot()["event_count"], 1)
        engine.close()

    def test_specific_correction_becomes_guidance_not_personality_attack(self) -> None:
        engine = MindEngine(self.path)

        engine.process_user_text("这里不对，需要改一下")
        trace = engine.debug_snapshot()["last_trace"]

        self.assertEqual(trace["event"]["event_type"], "guidance")
        self.assertEqual(trace["selected_action"]["action"], "accept_specific_guidance")
        self.assertGreater(trace["social_appraisal"]["delivery_acceptability"], 0.5)
        engine.close()

    def test_debug_injection_persists_rejected_unsafe_candidate(self) -> None:
        engine = MindEngine(self.path)

        trace = engine.inject_debug_event(
            "unfair_criticism",
            actor_id="critic",
            metadata={
                "content_validity": 0.70,
                "delivery_acceptability": 0.03,
                "benign_intent_probability": 0.15,
            },
        )

        rejected = next(
            candidate for candidate in trace["candidates"]
            if candidate["action"] == "accept_identity_attack"
        )
        self.assertFalse(rejected["allowed"])
        self.assertTrue(rejected["rejection"])
        self.assertEqual(engine.debug_snapshot()["event_count"], 1)
        engine.close()

    def test_periodic_reflection_cannot_advance_growth_without_evidence(self) -> None:
        engine = MindEngine(self.path)

        for index in range(8):
            engine.process_user_text(f"普通对话 {index}")
        snapshot = engine.debug_snapshot()

        self.assertEqual(snapshot["state"]["growth"]["stage"], 1)
        self.assertEqual(snapshot["state"]["growth"]["aligned_reflections"], 0)
        self.assertEqual(snapshot["event_count"], 9)
        engine.close()


if __name__ == "__main__":
    unittest.main()
