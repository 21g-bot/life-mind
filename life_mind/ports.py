"""Extension ports that keep the life core independent from any one host.

These are contracts, not claims that untrusted plugins are already sandboxed.
Capability adapters must not be loaded until a host supplies the permissioned
runtime described by the public roadmap.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from life_mind.ai import AIGeneration
from life_mind.contracts import CapabilityManifest, ExperienceRecord
from life_mind.presentation import PresentationIntent, RendererCapabilities


@runtime_checkable
class ExperienceSink(Protocol):
    """Only ingress allowed from an external capability into Mind Core."""

    def submit_experience(self, experience: ExperienceRecord) -> str: ...


@runtime_checkable
class PetRenderer(Protocol):
    """Sprite, Live2D, Spine, web or hardware presentation adapter."""

    def capabilities(self) -> RendererCapabilities: ...

    def present(self, intent: PresentationIntent) -> None: ...


@runtime_checkable
class ModelAdapter(Protocol):
    """Local or cloud language model with the same constrained output shape."""

    adapter_id: str

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        allow_reflection: bool,
    ) -> AIGeneration: ...


@runtime_checkable
class SpeechRecognitionAdapter(Protocol):
    adapter_id: str

    def transcribe(self, audio: bytes, *, sample_rate: int) -> str: ...


@runtime_checkable
class SpeechSynthesisAdapter(Protocol):
    adapter_id: str

    def synthesize(self, text: str, *, voice: str = "") -> bytes: ...


@runtime_checkable
class CapabilityAdapter(Protocol):
    """Lifecycle surface exposed only inside a future permissioned runtime."""

    manifest: CapabilityManifest

    def start(self, sink: ExperienceSink) -> None: ...

    def stop(self) -> None: ...


__all__ = (
    "CapabilityAdapter",
    "ExperienceSink",
    "ModelAdapter",
    "PetRenderer",
    "SpeechRecognitionAdapter",
    "SpeechSynthesisAdapter",
)
