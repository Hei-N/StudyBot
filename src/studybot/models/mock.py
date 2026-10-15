"""A deterministic, non-intelligent model for development and tests."""

from __future__ import annotations

from typing import Iterator, Sequence

from studybot.core.exceptions import ModelError
from studybot.core.messages import Message, Role
from studybot.core.reasoning_mode import DEFAULT_REASONING_MODE, ReasoningMode
from studybot.models.base import ModelCapabilities, ModelResponse, ProviderStatus


class MockModel:
    """Echoes the latest user message."""

    def __init__(self) -> None:
        self._name = "mock"

    @property
    def name(self) -> str:
        return self._name

    def _reply_to(self, messages: Sequence[Message]) -> str:
        last_user_message = next(
            (m for m in reversed(messages) if m.role is Role.USER), None
        )
        if last_user_message is None:
            raise ModelError("No user message found to respond to.")

        return f"[Mock] You said: {last_user_message.content}"

    def generate(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> ModelResponse:
        # The mock has no notion of thinking; the mode is accepted so every provider
        # can be called the same way.
        del reasoning_mode
        return ModelResponse(content=self._reply_to(messages), model_name=self._name)

    def stream(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> Iterator[str]:
        del reasoning_mode
        # One deterministic chunk satisfies the streaming interface.
        yield self._reply_to(messages)

    def get_status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_name=self._name,
            server_reachable=True,
            model_name=self._name,
            model_available=True,
        )

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            supports_vision=False,
            supports_tools=False,
            supports_thinking=False,
            reasoning_modes_distinct=False,
            context_window=None,
        )
