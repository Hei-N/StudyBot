"""Chat service: the core conversation logic, independent of any UI or backend.

Interfaces (CLI, future desktop UI, future macOS assistant) call into this
service. The service in turn calls a `ModelProvider`. Neither this module nor
its callers should know which concrete model backend is in use.
"""

from __future__ import annotations

import logging
from typing import Sequence

from studybot.core.messages import Message
from studybot.models.base import ModelProvider

logger = logging.getLogger(__name__)


class ChatService:
    """Manages in-memory conversation history for a single session."""

    def __init__(self, model: ModelProvider, system_prompt: str | None = None) -> None:
        self._model = model
        self._history: list[Message] = []
        if system_prompt:
            self._history.append(Message.system(system_prompt))

    @property
    def history(self) -> Sequence[Message]:
        """Read-only view of the conversation so far."""
        return tuple(self._history)

    def send(self, user_input: str) -> Message:
        """Add a user message, get a model response, and record it.

        Returns the assistant's reply message.
        """
        user_message = Message.user(user_input)
        self._history.append(user_message)
        logger.debug("Sending conversation of length %d to model", len(self._history))

        response = self._model.generate(self._history)

        assistant_message = Message.assistant(response.content)
        self._history.append(assistant_message)
        return assistant_message

    def clear(self) -> None:
        """Discard all conversation history for the current session."""
        self._history.clear()
        logger.debug("Chat history cleared")
