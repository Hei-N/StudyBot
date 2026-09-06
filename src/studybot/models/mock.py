"""A deterministic, non-intelligent model used for development and tests."""

from __future__ import annotations

from typing import Sequence

from studybot.core.exceptions import ModelError
from studybot.core.messages import Message, Role
from studybot.models.base import ModelResponse


class MockModel:
    """Echoes the latest user message. Makes no attempt to be intelligent."""

    def __init__(self) -> None:
        self._name = "mock"

    @property
    def name(self) -> str:
        return self._name

    def generate(self, messages: Sequence[Message]) -> ModelResponse:
        last_user_message = next(
            (m for m in reversed(messages) if m.role is Role.USER), None
        )
        if last_user_message is None:
            raise ModelError("No user message found to respond to.")

        return ModelResponse(
            content=f"[Mock] You said: {last_user_message.content}",
            model_name=self._name,
        )
