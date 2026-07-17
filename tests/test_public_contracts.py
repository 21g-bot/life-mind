from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from life_mind.contracts import (
    CapabilityManifest,
    ExperienceRecord,
    LifePackage,
    load_contract,
)
from life_mind.domain import EventType, PrivacyLevel


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def _example(name: str) -> dict[str, object]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class LifePackageContractTests(unittest.TestCase):
    def test_public_example_matches_published_json_schema(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "life-package.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(_example("life-package.demo.json"))

    def test_public_example_loads_and_round_trips(self) -> None:
        package = load_contract("life-package", EXAMPLES / "life-package.demo.json")

        self.assertIsInstance(package, LifePackage)
        self.assertEqual(package.package_id, "life-mind-demo-seed")
        self.assertEqual(LifePackage.from_dict(package.to_dict()), package)

    def test_initial_value_must_be_inside_declared_range(self) -> None:
        payload = _example("life-package.demo.json")
        payload["initialValues"]["persistence"] = 0.9  # type: ignore[index]

        with self.assertRaisesRegex(ValueError, "outside its temperament range"):
            LifePackage.from_dict(payload)

    def test_initial_value_requires_a_matching_range(self) -> None:
        payload = _example("life-package.demo.json")
        payload["initialValues"]["unknownTrait"] = 0.5  # type: ignore[index]

        with self.assertRaisesRegex(ValueError, "no matching temperament range"):
            LifePackage.from_dict(payload)

    def test_unknown_root_field_is_rejected(self) -> None:
        payload = _example("life-package.demo.json")
        payload["scriptedEnding"] = "always obey the user"

        with self.assertRaisesRegex(ValueError, "unknown fields"):
            LifePackage.from_dict(payload)


class CapabilityManifestContractTests(unittest.TestCase):
    def test_public_example_matches_published_json_schema(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "capability-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(_example("capability-manifest.demo.json"))

    def test_public_example_requires_explicit_user_grant(self) -> None:
        manifest = load_contract(
            "capability-manifest", EXAMPLES / "capability-manifest.demo.json"
        )

        self.assertIsInstance(manifest, CapabilityManifest)
        denied = manifest.authorize("ui:notification", set())
        allowed = manifest.authorize("ui:notification", {"ui:notification"})
        undeclared = manifest.authorize("observe:screen", {"observe:screen"})

        self.assertFalse(denied.allowed)
        self.assertTrue(allowed.allowed)
        self.assertFalse(undeclared.allowed)

    def test_protected_resource_and_subscope_are_never_grantable(self) -> None:
        base = _example("capability-manifest.demo.json")
        for permission in ("observe:credentials", "observe:private-messages.full"):
            with self.subTest(permission=permission):
                payload = copy.deepcopy(base)
                payload["permissions"] = [permission]
                with self.assertRaisesRegex(ValueError, "never grantable"):
                    CapabilityManifest.from_dict(payload)

    def test_network_access_requires_domain_allowlist(self) -> None:
        payload = _example("capability-manifest.demo.json")
        payload["permissions"] = ["network:approved-domains"]
        payload["networkAllowlist"] = []

        with self.assertRaisesRegex(ValueError, "networkAllowlist"):
            CapabilityManifest.from_dict(payload)

    def test_permission_has_exactly_one_namespace_separator(self) -> None:
        payload = _example("capability-manifest.demo.json")
        payload["permissions"] = ["observe:screen:raw"]

        with self.assertRaisesRegex(ValueError, "invalid permission"):
            CapabilityManifest.from_dict(payload)

    def test_allowlist_rejects_urls(self) -> None:
        payload = _example("capability-manifest.demo.json")
        payload["permissions"] = ["network:approved-domains"]
        payload["networkAllowlist"] = ["https://example.com/api"]

        with self.assertRaisesRegex(ValueError, "domains only"):
            CapabilityManifest.from_dict(payload)


class ExperienceProtocolContractTests(unittest.TestCase):
    def test_public_example_matches_published_json_schema(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "experience-protocol.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(_example("experience.demo.json"))

    def test_public_example_maps_to_existing_mind_event(self) -> None:
        experience = load_contract("experience", EXAMPLES / "experience.demo.json")

        self.assertIsInstance(experience, ExperienceRecord)
        event = experience.to_mind_event()

        self.assertEqual(event.event_type, EventType.AUTONOMOUS_ACTIVITY)
        self.assertEqual(event.actor_id, "companion")
        self.assertEqual(event.privacy, PrivacyLevel.PRIVATE)
        self.assertEqual(event.allowed_uses, ("state_update", "reflection"))
        self.assertAlmostEqual(event.confidence, 0.92)
        self.assertEqual(event.metadata["growth_candidates"], list(experience.growth_candidates))

    def test_privacy_allowed_uses_cannot_be_empty(self) -> None:
        payload = _example("experience.demo.json")
        payload["privacy"]["allowedUses"] = []  # type: ignore[index]

        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            ExperienceRecord.from_dict(payload)

    def test_emotional_impact_is_bounded(self) -> None:
        payload = _example("experience.demo.json")
        payload["emotionImpact"]["calm"] = 1.2  # type: ignore[index]

        with self.assertRaisesRegex(ValueError, "between -1.0 and 1.0"):
            ExperienceRecord.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
