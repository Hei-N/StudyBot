"""Model provider abstraction.

Every backend (mock, Ollama, a hosted API, a future router, ...) implements
`ModelProvider`. Nothing outside this module and its implementations should
know or care which concrete backend is in use.

`generate` is intentionally synchronous and returns a complete response. When
streaming is added later, it can be introduced as an additional method (e.g.
`stream(messages) -> Iterator[str]`) on this same protocol without changing
existing callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from studybot.core.messages import Message


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """The result of a single `generate` call."""

    content: str
    model_name: str


class ModelProvider(Protocol):
    """Interface implemented by every model backend."""

    @property
    def name(self) -> str:
        """A short identifier for the backend (e.g. 'mock', 'ollama')."""
        ...

    def generate(self, messages: Sequence[Message]) -> ModelResponse:
        """Produce a response given the full conversation so far.

        Implementations should raise `studybot.core.exceptions.ModelError`
        on failure rather than letting backend-specific exceptions escape.
        """
        ...
