from __future__ import annotations

import json
import unittest
import uuid
from copy import deepcopy
from pathlib import Path

from life_mind.growth_visibility import (
    build_blind_observation_card,
    derive_visible_growth,
)
from life_mind.mind import MindEngine
from life_mind.simulator import (
    HeadlessMindSimulator,
    build_stability_events,
    load_events,
    run_scenario,
)


class GrowthVisibilityTests(unittest.TestCase):
    def test_reference_arc_produces_cross_context_observations_and_artifacts(self) -> None:
        report = run_scenario(seed=731)

        visible = derive_visible_growth(report.final_state, report.traces)

        self.assertGreaterEqual(len(visible.signals), 6)
        self.assertGreaterEqual(len({item.context for item in visible.signals}), 4)
        artifact_ids = {item.artifact_id for item in visible.artifacts}
        self.assertIn("private_first_sketch", artifact_ids)
        self.assertIn("rest_boundary_note", artifact_ids)
        self.assertIn("ordinary_life_album", artifact_ids)
        self.assertTrue(all(item.evidence_event_ids for item in visible.artifacts))
        self.assertGreaterEqual(len(visible.potential_clues), 2)
        self.assertTrue(all(item.evidence_event_ids for item in visible.potential_clues))
        self.assertEqual(visible.weekly_chapter.title, "窗边留给自己的光")

    def test_hundred_quiet_days_do_not_unlock_advanced_keepsakes(self) -> None:
        simulator = HeadlessMindSimulator(seed=55)
        simulator.run(build_stability_events(100))

        visible = derive_visible_growth(
            simulator.state.to_dict(),
            [
                {
                    "event": trace.event,
                    "selected_action": trace.selected_action,
                    "notes": trace.notes,
                }
                for trace in simulator.traces
            ],
        )

        self.assertNotIn(
            "ordinary_life_album", {item.artifact_id for item in visible.artifacts}
        )

    def test_blind_card_does_not_leak_internal_gate_labels(self) -> None:
        report = run_scenario(seed=731)
        visible = derive_visible_growth(report.final_state, report.traces)

        card = build_blind_observation_card(visible, card_id="A")
        encoded = json.dumps(card, ensure_ascii=False).lower()

        for forbidden in ("stage", "growth", "阶段", "成长", "independent_value"):
            self.assertNotIn(forbidden, encoded)

    def test_redacted_events_cannot_unlock_visible_private_art(self) -> None:
        report = run_scenario(seed=731)
        traces = deepcopy(list(report.traces))
        for trace in traces:
            if trace["selected_action"]["action"] == "draw_private":
                trace["event"]["metadata"]["private_content_redacted"] = True
                trace["event"]["content"] = "[已删除的私人内容]"

        visible = derive_visible_growth(report.final_state, traces)

        self.assertNotIn(
            "private_first_sketch", {item.artifact_id for item in visible.artifacts}
        )

    def test_full_repair_unlocks_only_after_five_distinct_steps(self) -> None:
        simulator = HeadlessMindSimulator(seed=21)
        scenario = [
            {
                "event_id": "harm",
                "event_type": "unfair_criticism",
                "actor_id": "critic",
                "content": "具体错误与人格羞辱混在一起。",
            }
        ]
        for index, step in enumerate(
            ("acknowledgment", "responsibility", "remedy", "changed_behavior"), 1
        ):
            scenario.append(
                {
                    "event_id": f"repair-{index}",
                    "event_type": "repair",
                    "actor_id": "critic",
                    "content": "修复行为。",
                    "metadata": {"step": step},
                }
            )
        from life_mind.domain import MindEvent

        simulator.run(MindEvent.from_dict(item, i) for i, item in enumerate(scenario, 1))
        before = derive_visible_growth(
            simulator.state.to_dict(),
            [
                {
                    "event": trace.event,
                    "selected_action": trace.selected_action,
                    "notes": trace.notes,
                }
                for trace in simulator.traces
            ],
        )
        self.assertNotIn("retied_ribbon", {item.artifact_id for item in before.artifacts})

        simulator.apply_event(
            MindEvent.from_dict(
                {
                    "event_id": "repair-5",
                    "event_type": "repair",
                    "actor_id": "critic",
                    "content": "经过时间验证。",
                    "metadata": {"step": "time_evidence"},
                }
            )
        )
        after = derive_visible_growth(
            simulator.state.to_dict(),
            [
                {
                    "event": trace.event,
                    "selected_action": trace.selected_action,
                    "notes": trace.notes,
                }
                for trace in simulator.traces
            ],
        )
        ribbon = next(item for item in after.artifacts if item.artifact_id == "retied_ribbon")
        self.assertEqual(len(ribbon.evidence_event_ids), 5)

        redacted = [
            {
                "event": deepcopy(trace.event),
                "selected_action": trace.selected_action,
                "notes": trace.notes,
            }
            for trace in simulator.traces
        ]
        redacted[-1]["event"]["metadata"]["private_content_redacted"] = True
        redacted[-1]["event"]["content"] = "[已删除的私人内容]"
        hidden = derive_visible_growth(simulator.state.to_dict(), redacted)
        self.assertNotIn("retied_ribbon", {item.artifact_id for item in hidden.artifacts})

    def test_developer_evidence_replays_but_public_room_does_not_expose_it(self) -> None:
        path = Path(__file__).with_name(
            f"life-mind-growth-visibility-test-{uuid.uuid4().hex}.db"
        )
        for suffix in ("", "-wal", "-shm"):
            path.with_name(path.name + suffix).unlink(missing_ok=True)
        engine = None
        reopened = None
        try:
            engine = MindEngine(path)
            for event in load_events(Path("simulations/demo_growth.json")):
                engine.runtime.apply(event)
            engine._sync_runtime_state()
            engine.connection.commit()
            before = engine.debug_snapshot()["visible_growth"]
            public_before = engine.public_room_snapshot()
            engine.close()
            engine.connection.close()
            engine = None

            reopened = MindEngine(path)
            after = reopened.debug_snapshot()["visible_growth"]
            public_after = reopened.public_room_snapshot()
            reopened.close()
            reopened.connection.close()
            reopened = None
        finally:
            if engine is not None:
                engine.connection.close()
            if reopened is not None:
                reopened.connection.close()
            for suffix in ("", "-wal", "-shm"):
                path.with_name(path.name + suffix).unlink(missing_ok=True)

        self.assertEqual(before, after)
        self.assertEqual(public_before, public_after)
        self.assertNotIn("visible_growth", public_before)
        self.assertNotIn("growth", public_before)


if __name__ == "__main__":
    unittest.main()
