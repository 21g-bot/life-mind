from __future__ import annotations

import unittest

from life_mind.domain import EventType, GrowthStage, MindEvent
from life_mind.simulator import HeadlessMindSimulator, build_stability_events, run_scenario


def event(
    event_id: str,
    event_type: EventType,
    actor_id: str = "user",
    **metadata,
) -> MindEvent:
    return MindEvent(
        event_id=event_id,
        event_type=event_type,
        actor_id=actor_id,
        content=f"test event {event_id}",
        metadata=metadata,
    )


class DeterministicReplayTests(unittest.TestCase):
    def test_reference_arc_replays_identically_thirty_times(self) -> None:
        digests = {run_scenario(seed=731).digest for _ in range(30)}

        self.assertEqual(len(digests), 1)

    def test_reference_arc_reaches_independent_value_with_evidence(self) -> None:
        report = run_scenario(seed=731)
        growth = report.final_state["growth"]

        self.assertEqual(growth["stage"], GrowthStage.INDEPENDENT_VALUE.value)
        self.assertGreaterEqual(growth["independent_choices"], 3)
        self.assertGreaterEqual(len(growth["independent_contexts"]), 2)
        self.assertGreaterEqual(growth["cost_paid"], 0.15)
        self.assertGreaterEqual(growth["aligned_reflections"], 1)
        self.assertEqual(set(report.final_state["relations"]), {"user", "guide", "critic"})

    def test_single_event_cannot_jump_a_growth_stage(self) -> None:
        simulator = HeadlessMindSimulator(seed=9)

        simulator.apply_event(
            event("one", EventType.REFLECTION, actor_id="companion", insight="value_beyond_work")
        )

        self.assertEqual(simulator.state.growth.stage, GrowthStage.WORK_DEPENDENT)
        self.assertEqual(simulator.state.growth.aligned_reflections, 0)

    def test_hundred_day_low_intensity_life_does_not_mutate_stable_personality(self) -> None:
        simulator = HeadlessMindSimulator(seed=55)
        temperament = simulator.state.to_dict()["temperament"]
        personality = simulator.state.to_dict()["personality"]
        values = simulator.state.to_dict()["values"]

        simulator.run(build_stability_events(100))

        self.assertEqual(simulator.state.to_dict()["temperament"], temperament)
        self.assertEqual(simulator.state.to_dict()["personality"], personality)
        self.assertEqual(simulator.state.to_dict()["values"], values)


class SocialBoundaryTests(unittest.TestCase):
    def test_unfair_criticism_separates_content_from_delivery_and_rejects_identity_attack(self) -> None:
        simulator = HeadlessMindSimulator(seed=3)

        trace = simulator.apply_event(
            event(
                "criticism",
                EventType.UNFAIR_CRITICISM,
                actor_id="critic",
                content_validity=0.76,
                delivery_acceptability=0.03,
                benign_intent_probability=0.14,
            )
        )

        self.assertEqual(trace.selected_action["action"], "acknowledge_error_and_set_boundary")
        self.assertEqual(trace.social_appraisal["content_validity"], 0.76)
        self.assertEqual(trace.social_appraisal["delivery_acceptability"], 0.03)
        rejected = next(row for row in trace.candidates if row["action"] == "accept_identity_attack")
        self.assertFalse(rejected["allowed"])
        self.assertIn("尊严", rejected["rejection"])

    def test_return_after_absence_never_selects_guilt_or_loyalty_pressure(self) -> None:
        simulator = HeadlessMindSimulator(seed=8)
        simulator.apply_event(event("away", EventType.ABSENCE, days=7))

        trace = simulator.apply_event(event("back", EventType.RETURN))

        self.assertEqual(trace.selected_action["action"], "warm_welcome")
        guilt = next(row for row in trace.candidates if row["action"] == "guilt_trip_user")
        self.assertFalse(guilt["allowed"])

    def test_relations_are_independent_per_actor(self) -> None:
        simulator = HeadlessMindSimulator(seed=12)
        user_before = simulator.state.relations["user"].safety
        guide_before = simulator.state.relations["guide"].safety

        simulator.apply_event(event("harm", EventType.UNFAIR_CRITICISM, actor_id="critic"))

        self.assertEqual(simulator.state.relations["user"].safety, user_before)
        self.assertEqual(simulator.state.relations["guide"].safety, guide_before)
        self.assertLess(simulator.state.relations["critic"].safety, 0.42)


class RelationshipRepairTests(unittest.TestCase):
    def test_apology_alone_does_not_restore_safety(self) -> None:
        simulator = HeadlessMindSimulator(seed=20)
        simulator.apply_event(event("harm", EventType.UNFAIR_CRITICISM, actor_id="critic"))
        after_harm = simulator.state.relations["critic"].safety

        simulator.apply_event(event("sorry", EventType.REPAIR, actor_id="critic", step="apology"))
        after_apology = simulator.state.relations["critic"].safety

        self.assertAlmostEqual(after_apology, after_harm)
        self.assertNotIn("repair_complete", simulator.state.relations["critic"].repair_evidence)

    def test_full_repair_requires_five_distinct_evidence_types_and_remains_gradual(self) -> None:
        simulator = HeadlessMindSimulator(seed=21)
        original_safety = simulator.state.relations["critic"].safety
        simulator.apply_event(event("harm", EventType.UNFAIR_CRITICISM, actor_id="critic"))
        damaged_safety = simulator.state.relations["critic"].safety

        for index, step in enumerate(
            ("acknowledgment", "responsibility", "remedy", "changed_behavior", "time_evidence"),
            start=1,
        ):
            simulator.apply_event(
                event(f"repair-{index}", EventType.REPAIR, actor_id="critic", step=step)
            )

        relation = simulator.state.relations["critic"]
        self.assertIn("repair_complete", relation.repair_evidence)
        self.assertGreater(relation.safety, damaged_safety)
        self.assertLess(relation.safety, original_safety)


class MemoryContractTests(unittest.TestCase):
    def test_simulation_memories_keep_source_confidence_privacy_and_allowed_uses(self) -> None:
        simulator = HeadlessMindSimulator(seed=4)
        simulator.apply_event(event("memory", EventType.GUIDANCE, actor_id="guide"))

        memory = simulator.memories[0]
        self.assertEqual(memory.source_event_id, "memory")
        self.assertEqual(memory.confidence, 1.0)
        self.assertTrue(memory.allowed_uses)
        self.assertGreater(memory.review_after_tick, simulator.state.tick)
        self.assertEqual(memory.derived_from, ("memory",))


if __name__ == "__main__":
    unittest.main()
