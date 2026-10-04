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
from studybot.core.reasoning_mode import DEFAULT_REASONING_MODE, ReasoningMode


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

    def generate(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> ModelResponse:
        """Produce a complete response given the full conversation so far.

        `reasoning_mode` is a generic preference — how much inference-time
        "thinking" to do before answering — passed through explicitly by
        the caller rather than left to the backend's own default. A
        provider with no such concept is free to ignore it, deliberately
        (see e.g. `MockModel`); nothing above this layer (`ChatService`,
        `SessionService`) knows or cares which concrete backend, if any,
        actually acts on it.

        Implementations should raise `studybot.core.exceptions.ModelError`
        on failure rather than letting backend-specific exceptions escape.
        A provider must never return hidden reasoning/thinking text as part
        of `ModelResponse.content` — only the final, user-visible answer.
        """
        ...

    def stream(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> Iterator[str]:
        """Produce a response incrementally, yielding content chunks.

        Concatenating all yielded chunks must equal what `generate` would
        have returned as `ModelResponse.content` for the same input, given
        the same `reasoning_mode` (see `generate`). Implementations should
        raise `ModelError` (before yielding anything, or by letting the
        exception propagate out of iteration) rather than letting
        backend-specific exceptions escape. Hidden reasoning/thinking
        chunks, if the backend emits them, must never be yielded here —
        only user-visible content.

        An empty string is a *progress signal*, not content: providers may
        yield `""` while the model is working without producing visible
        text yet (e.g. reasoning). Callers that display or send chunks
        skip empty ones. It exists because the API runs each `next()` on
        its single engine thread (`api/websocket.py`): a provider that sat
        silently inside one `next()` for a minute of reasoning would block
        every other request — health checks included — for that long.
        """
        ...

    def get_status(self) -> ProviderStatus:
        """Check current health: is the backend reachable, is the
        configured model available. Call only when status is actually
        needed (e.g. a `/status` command) — not on a timer."""
        ...
