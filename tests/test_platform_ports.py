from __future__ import annotations

import unittest

from life_mind.ports import PetRenderer
from life_mind.presentation import (
    PetState,
    PresentationIntent,
    RendererCapabilities,
    project_trace,
)


class FakeRenderer:
    def __init__(self) -> None:
        self.received: list[PresentationIntent] = []

    def capabilities(self) -> RendererCapabilities:
        return RendererCapabilities(
            "test-renderer", ("idle", "work", "happy", "curious", "sleep")
        )

    def present(self, intent: PresentationIntent) -> None:
        self.received.append(intent)


def trace(action: str, event_id: str = "evt-1") -> dict[str, object]:
    return {
        "event": {"event_id": event_id, "private_payload": "must-not-leak"},
        "selected_action": {"action": action, "explanation": "private reason"},
        "state_after": {"relations": {"user": {"trust_goodwill": 0.7}}},
    }


class RendererCapabilitiesTests(unittest.TestCase):
    def test_idle_fallback_is_mandatory(self) -> None:
        with self.assertRaisesRegex(ValueError, "idle fallback"):
            RendererCapabilities("sprite", ("work",))

    def test_unknown_clip_resolves_without_changing_character_scale(self) -> None:
        capabilities = RendererCapabilities("sprite", ("idle", "work"))
        self.assertEqual(capabilities.resolve_clip("missing"), "idle")

    def test_renderer_identifier_and_fps_are_strict(self) -> None:
        with self.assertRaisesRegex(ValueError, "renderer_id"):
            RendererCapabilities(" sprite ", ("idle",))
        with self.assertRaisesRegex(ValueError, "max_fps"):
            RendererCapabilities("sprite", ("idle",), max_fps="30")  # type: ignore[arg-type]


class PresentationProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.renderer = FakeRenderer()

    def test_fake_renderer_satisfies_public_port(self) -> None:
        self.assertIsInstance(self.renderer, PetRenderer)

    def test_task_decision_compresses_to_busy_state(self) -> None:
        intent = project_trace(trace("accept_task"), self.renderer.capabilities())

        self.assertEqual(intent.state, PetState.BUSY)
        self.assertEqual(intent.clip, "work")
        self.assertEqual(intent.source_event_id, "evt-1")

    def test_question_and_success_have_readable_symbols(self) -> None:
        attention = project_trace(
            trace("ask_for_clarification"), self.renderer.capabilities()
        )
        success = project_trace(trace("report_success"), self.renderer.capabilities())

        self.assertEqual((attention.state, attention.symbol), (PetState.ATTENTION, "?"))
        self.assertEqual((success.state, success.symbol), (PetState.CELEBRATE, "!"))

    def test_private_life_is_not_collapsed_into_user_work(self) -> None:
        intent = project_trace(trace("draw_private"), self.renderer.capabilities())

        self.assertEqual(intent.state, PetState.PRIVATE_LIFE)
        self.assertEqual(intent.clip, "idle")

    def test_projection_does_not_expose_internal_state_or_explanation(self) -> None:
        payload = project_trace(
            trace("acknowledge_error_and_set_boundary"), self.renderer.capabilities()
        ).to_dict()

        self.assertEqual(payload["state"], "pensive")
        serialized = repr(payload)
        self.assertNotIn("trust_goodwill", serialized)
        self.assertNotIn("private reason", serialized)
        self.assertNotIn("private_payload", serialized)

    def test_renderer_without_symbol_support_receives_no_symbol(self) -> None:
        capabilities = RendererCapabilities(
            "minimal-host", ("idle", "curious"), supports_symbols=False
        )
        intent = project_trace(trace("ask_for_clarification"), capabilities)

        self.assertEqual(intent.symbol, "")

    def test_intent_rejects_unbounded_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "160"):
            PresentationIntent(PetState.IDLE, "idle", text="x" * 161)

    def test_intent_rejects_untyped_public_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "PetState"):
            PresentationIntent("idle", "idle")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
