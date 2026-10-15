"""Model provider interface.

Every backend (mock, Ollama, a hosted API, ...) implements ``ModelProvider``;
code outside this module and its implementations does not depend on which one
is in use. ``generate`` returns a complete response and ``stream`` yields it
incrementally.
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
    """A snapshot of a provider's health, produced on demand rather than polled."""

    provider_name: str
    server_reachable: bool
    model_name: str
    model_available: bool | None
    """None if unknown (e.g. the server is unreachable)."""
    detail: str | None = None
    """Optional human-readable detail, e.g. a connection hint."""


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """What a provider's model reports it can do.

    Each flag is True (reported supported), False (reported unsupported) or None
    (could not be determined). This describes the model, not StudyBot:
    ``supports_vision=True`` does not mean the text-only ``Message`` pipeline can
    send an image.
    """

    supports_vision: bool | None
    supports_tools: bool | None
    supports_thinking: bool | None
    reasoning_modes_distinct: bool | None
    """Whether Fast and Deep genuinely differ. False for an always-thinking
    model (both modes must reason) and for a model without thinking."""
    context_window: int | None
    """Advertised maximum context length in tokens. Not the (smaller) context
    the server is currently configured to use."""


class ModelProvider(Protocol):
    """Interface implemented by every model backend."""

    @property
    def name(self) -> str:
        """Short backend identifier, e.g. 'mock' or 'ollama'."""
        ...

    def generate(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> ModelResponse:
        """Return a complete response for the conversation so far.

        ``reasoning_mode`` is a generic preference for how much hidden "thinking" to
        do; a provider with no such concept may ignore it. Implementations raise
        ``ModelError`` on failure and must never return hidden reasoning, only the
        final answer.
        """
        ...

    def stream(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> Iterator[str]:
        """Yield the response incrementally.

        The concatenated chunks equal what ``generate`` returns for the same input.
        Failures raise ``ModelError``; hidden reasoning is never yielded.

        An empty string is a progress signal, not content. Providers yield it while
        the model is working without visible output so the API's single engine thread
        can serve other requests in between. Consumers skip empty chunks.
        """
        ...

    def get_status(self) -> ProviderStatus:
        """Return current backend health. Call on demand, not on a timer."""
        ...

    def get_capabilities(self) -> ModelCapabilities:
        """Return what the model reports it supports.

        Values are discovered, never inferred from the model name; unknown values are
        None. May perform a cached metadata lookup and does not raise if the backend
        is unreachable.
        """
        ...
