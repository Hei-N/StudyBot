"""A deterministic, non-intelligent model used for development and tests."""

from __future__ import annotations

from typing import Iterator, Sequence

from studybot.core.exceptions import ModelError
from studybot.core.messages import Message, Role
from studybot.models.base import ModelResponse, ProviderStatus


class MockModel:
    """Echoes the latest user message. Makes no attempt to be intelligent."""

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

    def generate(self, messages: Sequence[Message]) -> ModelResponse:
        return ModelResponse(content=self._reply_to(messages), model_name=self._name)

    def stream(self, messages: Sequence[Message]) -> Iterator[str]:
        # Deterministic single chunk: the mock has nothing to stream
        # progressively, but must still satisfy the streaming interface.
        yield self._reply_to(messages)

    def get_status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_name=self._name,
            server_reachable=True,
            model_name=self._name,
            model_available=True,
        )
