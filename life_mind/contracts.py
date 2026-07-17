"""Public, model-free contracts for LIFE-Mind packages and integrations.

These contracts deliberately use only the Python standard library.  The JSON
schemas in ``schemas/`` are the language-neutral interchange format; these
dataclasses provide the runtime validation used by the reference host.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from life_mind.domain import EventType, MindEvent, PrivacyLevel


CONTRACT_VERSION = "0.1"
PACKAGE_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:[-+][a-zA-Z0-9.-]+)?$")
DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.I)
PERMISSION_PREFIXES = frozenset(
    {"observe", "memory", "action", "share", "network", "device", "ui"}
)
NON_GRANTABLE_CAPABILITIES = frozenset(
    {"credentials", "private-messages", "background-surveillance"}
)
EXPERIENCE_ROLES = frozenset({"user", "agent", "system", "environment", "tool", "other"})


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return {str(key): item for key, item in value.items()}


def _strict_keys(payload: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(payload).difference(allowed))
    if unknown:
        raise ValueError(f"{name} contains unknown fields: {', '.join(unknown)}")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _strings(value: object, name: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    items = tuple(_text(item, f"{name} item") for item in value)
    if required and not items:
        raise ValueError(f"{name} cannot be empty")
    if len(set(items)) != len(items):
        raise ValueError(f"{name} cannot contain duplicates")
    return items


def _number(value: object, name: str, lower: float, upper: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    result = float(value)
    if not lower <= result <= upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return result


def _identifier(value: object, name: str) -> str:
    result = _text(value, name)
    if not PACKAGE_ID.fullmatch(result):
        raise ValueError(f"{name} must use lowercase letters, numbers, dots, dashes or underscores")
    return result


def _is_non_grantable_resource(resource: str) -> bool:
    """Reject a protected namespace as well as any of its sub-scopes."""

    return any(
        resource == blocked or resource.startswith(f"{blocked}.")
        for blocked in NON_GRANTABLE_CAPABILITIES
    )


@dataclass(frozen=True, slots=True)
class ValueRange:
    minimum: float
    maximum: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum <= self.maximum <= 1.0:
            raise ValueError("value range must satisfy 0 <= minimum <= maximum <= 1")

    @classmethod
    def from_value(cls, value: object, name: str) -> "ValueRange":
        if isinstance(value, (list, tuple)) and len(value) == 2:
            minimum = _number(value[0], f"{name}[0]", 0.0, 1.0)
            maximum = _number(value[1], f"{name}[1]", 0.0, 1.0)
            return cls(minimum, maximum)
        payload = _mapping(value, name)
        _strict_keys(payload, {"min", "max"}, name)
        return cls(
            _number(payload.get("min"), f"{name}.min", 0.0, 1.0),
            _number(payload.get("max"), f"{name}.max", 0.0, 1.0),
        )

    def to_dict(self) -> dict[str, float]:
        return {"min": self.minimum, "max": self.maximum}


@dataclass(frozen=True, slots=True)
class ContentLicense:
    spdx: str
    assets: str
    attribution: str
    redistributable: bool

    @classmethod
    def from_dict(cls, value: object) -> "ContentLicense":
        payload = _mapping(value, "contentLicense")
        _strict_keys(payload, {"spdx", "assets", "attribution", "redistributable"}, "contentLicense")
        redistributable = payload.get("redistributable")
        if not isinstance(redistributable, bool):
            raise ValueError("contentLicense.redistributable must be a boolean")
        return cls(
            spdx=_text(payload.get("spdx"), "contentLicense.spdx"),
            assets=_text(payload.get("assets"), "contentLicense.assets"),
            attribution=_text(payload.get("attribution"), "contentLicense.attribution"),
            redistributable=redistributable,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "spdx": self.spdx,
            "assets": self.assets,
            "attribution": self.attribution,
            "redistributable": self.redistributable,
        }


@dataclass(frozen=True, slots=True)
class LifePackage:
    schema_version: str
    package_id: str
    compatibility: dict[str, Any]
    identity: dict[str, Any]
    visuals: dict[str, Any]
    animations: dict[str, Any]
    voice: dict[str, Any]
    temperament_ranges: dict[str, ValueRange]
    initial_values: dict[str, float]
    possible_conflicts: tuple[str, ...]
    latent_trait_pool: tuple[str, ...]
    expression_style: dict[str, Any]
    growth_constraints: dict[str, Any]
    content_license: ContentLicense

    @classmethod
    def from_dict(cls, value: object) -> "LifePackage":
        payload = _mapping(value, "Life Package")
        allowed = {
            "schemaVersion", "packageId", "compatibility", "identity", "visuals",
            "animations", "voice", "temperamentRanges", "initialValues",
            "possibleConflicts", "latentTraitPool", "expressionStyle",
            "growthConstraints", "contentLicense",
        }
        _strict_keys(payload, allowed, "Life Package")
        schema_version = _text(payload.get("schemaVersion"), "schemaVersion")
        if schema_version != CONTRACT_VERSION:
            raise ValueError(f"unsupported Life Package schemaVersion: {schema_version}")

        compatibility = _mapping(payload.get("compatibility"), "compatibility")
        _text(compatibility.get("lifeMind"), "compatibility.lifeMind")
        identity = _mapping(payload.get("identity"), "identity")
        _text(identity.get("kind"), "identity.kind")
        _text(identity.get("displayName"), "identity.displayName")
        visuals = _mapping(payload.get("visuals"), "visuals")
        _text(visuals.get("renderer"), "visuals.renderer")
        animations = _mapping(payload.get("animations"), "animations")
        _text(animations.get("manifest"), "animations.manifest")
        voice = _mapping(payload.get("voice", {}), "voice")

        raw_ranges = _mapping(payload.get("temperamentRanges"), "temperamentRanges")
        if not raw_ranges:
            raise ValueError("temperamentRanges cannot be empty")
        ranges = {
            name: ValueRange.from_value(item, f"temperamentRanges.{name}")
            for name, item in raw_ranges.items()
        }
        raw_initial = _mapping(payload.get("initialValues"), "initialValues")
        initial = {
            name: _number(item, f"initialValues.{name}", 0.0, 1.0)
            for name, item in raw_initial.items()
        }
        for name, number in initial.items():
            allowed_range = ranges.get(name)
            if allowed_range is None:
                raise ValueError(f"initialValues.{name} has no matching temperament range")
            if not allowed_range.minimum <= number <= allowed_range.maximum:
                raise ValueError(f"initialValues.{name} is outside its temperament range")

        growth = _mapping(payload.get("growthConstraints"), "growthConstraints")
        max_active_arcs = growth.get("maxActiveArcs", 1)
        if isinstance(max_active_arcs, bool) or not isinstance(max_active_arcs, int) or max_active_arcs < 1:
            raise ValueError("growthConstraints.maxActiveArcs must be a positive integer")

        return cls(
            schema_version=schema_version,
            package_id=_identifier(payload.get("packageId"), "packageId"),
            compatibility=compatibility,
            identity=identity,
            visuals=visuals,
            animations=animations,
            voice=voice,
            temperament_ranges=ranges,
            initial_values=initial,
            possible_conflicts=_strings(payload.get("possibleConflicts", []), "possibleConflicts"),
            latent_trait_pool=_strings(payload.get("latentTraitPool", []), "latentTraitPool"),
            expression_style=_mapping(payload.get("expressionStyle"), "expressionStyle"),
            growth_constraints=growth,
            content_license=ContentLicense.from_dict(payload.get("contentLicense")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "packageId": self.package_id,
            "compatibility": self.compatibility,
            "identity": self.identity,
            "visuals": self.visuals,
            "animations": self.animations,
            "voice": self.voice,
            "temperamentRanges": {
                name: item.to_dict() for name, item in sorted(self.temperament_ranges.items())
            },
            "initialValues": dict(sorted(self.initial_values.items())),
            "possibleConflicts": list(self.possible_conflicts),
            "latentTraitPool": list(self.latent_trait_pool),
            "expressionStyle": self.expression_style,
            "growthConstraints": self.growth_constraints,
            "contentLicense": self.content_license.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    schema_version: str
    capability_id: str
    version: str
    name: str
    permissions: tuple[str, ...]
    forbidden: tuple[str, ...]
    data_scopes: tuple[str, ...]
    network_allowlist: tuple[str, ...]
    rate_limits: dict[str, int]

    @classmethod
    def from_dict(cls, value: object) -> "CapabilityManifest":
        payload = _mapping(value, "Capability Manifest")
        allowed = {
            "schemaVersion", "id", "version", "name", "permissions", "forbidden",
            "dataScopes", "networkAllowlist", "rateLimits",
        }
        _strict_keys(payload, allowed, "Capability Manifest")
        schema_version = _text(payload.get("schemaVersion"), "schemaVersion")
        if schema_version != CONTRACT_VERSION:
            raise ValueError(f"unsupported Capability Manifest schemaVersion: {schema_version}")
        version = _text(payload.get("version"), "version")
        if not VERSION.fullmatch(version):
            raise ValueError("version must be a semantic version")
        permissions = _strings(payload.get("permissions"), "permissions", required=True)
        for permission in permissions:
            prefix, separator, resource = permission.partition(":")
            if (
                not separator
                or prefix not in PERMISSION_PREFIXES
                or not resource
                or ":" in resource
            ):
                raise ValueError(f"invalid permission: {permission}")
            if _is_non_grantable_resource(resource):
                raise ValueError(f"permission is never grantable: {permission}")
        forbidden = _strings(payload.get("forbidden", []), "forbidden")
        data_scopes = _strings(payload.get("dataScopes", []), "dataScopes")
        allowlist = _strings(payload.get("networkAllowlist", []), "networkAllowlist")
        for domain in allowlist:
            if not DOMAIN.fullmatch(domain) or "://" in domain or "/" in domain:
                raise ValueError(f"networkAllowlist must contain domains only: {domain}")
        if any(item.startswith("network:") for item in permissions) and not allowlist:
            raise ValueError("network permissions require a non-empty networkAllowlist")

        raw_limits = _mapping(payload.get("rateLimits"), "rateLimits")
        limits: dict[str, int] = {}
        for key, item in raw_limits.items():
            if isinstance(item, bool) or not isinstance(item, int) or item < 1:
                raise ValueError(f"rateLimits.{key} must be a positive integer")
            limits[key] = item
        if not limits:
            raise ValueError("rateLimits cannot be empty")
        return cls(
            schema_version=schema_version,
            capability_id=_identifier(payload.get("id"), "id"),
            version=version,
            name=_text(payload.get("name"), "name"),
            permissions=permissions,
            forbidden=forbidden,
            data_scopes=data_scopes,
            network_allowlist=allowlist,
            rate_limits=limits,
        )

    def authorize(self, permission: str, user_grants: set[str] | frozenset[str]) -> CapabilityDecision:
        resource = permission.partition(":")[2]
        if _is_non_grantable_resource(resource):
            return CapabilityDecision(False, "permission is never grantable")
        if permission not in self.permissions:
            return CapabilityDecision(False, "permission is not declared by the capability")
        if permission not in user_grants:
            return CapabilityDecision(False, "permission has not been granted by the user")
        if permission in self.forbidden or resource in self.forbidden:
            return CapabilityDecision(False, "permission is forbidden by the manifest")
        return CapabilityDecision(True, "declared and explicitly granted")

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "id": self.capability_id,
            "version": self.version,
            "name": self.name,
            "permissions": list(self.permissions),
            "forbidden": list(self.forbidden),
            "dataScopes": list(self.data_scopes),
            "networkAllowlist": list(self.network_allowlist),
            "rateLimits": dict(sorted(self.rate_limits.items())),
        }


@dataclass(frozen=True, slots=True)
class ExperienceRecord:
    schema_version: str
    event_id: str
    event_type: EventType
    source: str
    role: str
    actors: tuple[str, ...]
    observation: dict[str, Any]
    interpretation: dict[str, Any]
    uncertainty: float
    emotion_impact: dict[str, float]
    action: dict[str, Any]
    outcome: dict[str, Any]
    privacy: dict[str, Any]
    growth_candidates: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: object) -> "ExperienceRecord":
        payload = _mapping(value, "Experience Protocol")
        allowed = {
            "schemaVersion", "eventId", "eventType", "source", "role", "actors",
            "observation", "interpretation", "uncertainty", "emotionImpact", "action",
            "outcome", "privacy", "growthCandidates",
        }
        _strict_keys(payload, allowed, "Experience Protocol")
        schema_version = _text(payload.get("schemaVersion"), "schemaVersion")
        if schema_version != CONTRACT_VERSION:
            raise ValueError(f"unsupported Experience Protocol schemaVersion: {schema_version}")
        role = _text(payload.get("role"), "role")
        if role not in EXPERIENCE_ROLES:
            raise ValueError(f"unsupported experience role: {role}")
        observation = _mapping(payload.get("observation"), "observation")
        _text(observation.get("summary"), "observation.summary")
        privacy = _mapping(payload.get("privacy"), "privacy")
        privacy_level = _text(privacy.get("level"), "privacy.level")
        try:
            PrivacyLevel(privacy_level)
        except ValueError as exc:
            raise ValueError(f"unsupported privacy level: {privacy_level}") from exc
        _strings(privacy.get("allowedUses"), "privacy.allowedUses", required=True)
        raw_impact = _mapping(payload.get("emotionImpact", {}), "emotionImpact")
        impact = {
            name: _number(item, f"emotionImpact.{name}", -1.0, 1.0)
            for name, item in raw_impact.items()
        }
        try:
            event_type = EventType(str(payload.get("eventType", EventType.CONVERSATION.value)))
        except ValueError as exc:
            raise ValueError(f"unsupported eventType: {payload.get('eventType')}") from exc
        return cls(
            schema_version=schema_version,
            event_id=_text(payload.get("eventId"), "eventId"),
            event_type=event_type,
            source=_text(payload.get("source"), "source"),
            role=role,
            actors=_strings(payload.get("actors"), "actors", required=True),
            observation=observation,
            interpretation=_mapping(payload.get("interpretation"), "interpretation"),
            uncertainty=_number(payload.get("uncertainty"), "uncertainty", 0.0, 1.0),
            emotion_impact=impact,
            action=_mapping(payload.get("action", {}), "action"),
            outcome=_mapping(payload.get("outcome", {}), "outcome"),
            privacy=privacy,
            growth_candidates=_strings(payload.get("growthCandidates", []), "growthCandidates"),
        )

    def to_mind_event(self) -> MindEvent:
        allowed_uses = _strings(
            self.privacy.get("allowedUses"), "privacy.allowedUses", required=True
        )
        return MindEvent(
            event_id=self.event_id,
            event_type=self.event_type,
            actor_id=self.actors[0],
            content=str(self.observation["summary"]),
            source=self.source,
            confidence=round(1.0 - self.uncertainty, 6),
            privacy=PrivacyLevel(str(self.privacy["level"])),
            allowed_uses=allowed_uses,
            metadata={
                "experience_role": self.role,
                "actors": list(self.actors),
                "observation": self.observation,
                "interpretation": self.interpretation,
                "emotion_impact": self.emotion_impact,
                "action": self.action,
                "outcome": self.outcome,
                "growth_candidates": list(self.growth_candidates),
            },
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "eventId": self.event_id,
            "eventType": self.event_type.value,
            "source": self.source,
            "role": self.role,
            "actors": list(self.actors),
            "observation": self.observation,
            "interpretation": self.interpretation,
            "uncertainty": self.uncertainty,
            "emotionImpact": dict(sorted(self.emotion_impact.items())),
            "action": self.action,
            "outcome": self.outcome,
            "privacy": self.privacy,
            "growthCandidates": list(self.growth_candidates),
        }


CONTRACT_TYPES = {
    "life-package": LifePackage,
    "capability-manifest": CapabilityManifest,
    "experience": ExperienceRecord,
}


def validate_contract(kind: str, value: object) -> LifePackage | CapabilityManifest | ExperienceRecord:
    contract_type = CONTRACT_TYPES.get(kind)
    if contract_type is None:
        raise ValueError(f"unknown contract kind: {kind}")
    return contract_type.from_dict(value)


def load_contract(kind: str, path: Path) -> LifePackage | CapabilityManifest | ExperienceRecord:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_contract(kind, payload)


__all__ = (
    "CONTRACT_TYPES",
    "CONTRACT_VERSION",
    "CapabilityDecision",
    "CapabilityManifest",
    "ContentLicense",
    "ExperienceRecord",
    "LifePackage",
    "ValueRange",
    "load_contract",
    "validate_contract",
)
