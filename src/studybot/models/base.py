"""Model provider abstraction.

Every backend (mock, Ollama, a hosted API, a future router, ...) implements
`ModelProvider`. Nothing outside this module and its implementations should
know or care which concrete backend is in use.

`generate` returns a complete response and is the simplest path for callers
(and tests) that don't need progressive output. `stream` yields response
content incrementally for interfaces that want to display tokens as they
arrive; both exist side by side rather than streaming replacing the
non-streaming path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Protocol, Sequence

from studybot.core.messages import Message


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """The result of a single `generate` call."""

    content: str
    model_name: str


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    """A point-in-time snapshot of a provider's health.

    Produced on demand (e.g. for a CLI `/status` command) — providers must
    not poll continuously to keep this up to date.
    """

    provider_name: str
    server_reachable: bool
    model_name: str
    model_available: bool | None
    """True/False if known; None if it couldn't be determined (e.g. the
    server itself is unreachable, or the provider has no such concept)."""
    detail: str | None = None
    """Optional human-readable elaboration, e.g. a connection error hint."""


class ModelProvider(Protocol):
    """Interface implemented by every model backend."""

    @property
    def name(self) -> str:
        """A short identifier for the backend (e.g. 'mock', 'ollama')."""
        ...

    def generate(self, messages: Sequence[Message]) -> ModelResponse:
        """Produce a complete response given the full conversation so far.

        Implementations should raise `studybot.core.exceptions.ModelError`
        on failure rather than letting backend-specific exceptions escape.
        """
        ...

    def stream(self, messages: Sequence[Message]) -> Iterator[str]:
        """Produce a response incrementally, yielding content chunks.

        Concatenating all yielded chunks must equal what `generate` would
        have returned as `ModelResponse.content` for the same input.
        Implementations should raise `ModelError` (before yielding anything,
        or by letting the exception propagate out of iteration) rather than
        letting backend-specific exceptions escape.
        """
        ...

    def get_status(self) -> ProviderStatus:
        """Check current health: is the backend reachable, is the
        configured model available. Call only when status is actually
        needed (e.g. a `/status` command) — not on a timer."""
        ...
