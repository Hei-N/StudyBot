"""Conversation logic for a single chat, independent of any UI or model backend.

``ChatService`` keeps the in-memory history and calls a ``ModelProvider``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Iterator, Sequence

from studybot.core.messages import Message, Role
from studybot.core.output_integrity import strip_confident_reasoning
from studybot.core.reasoning_mode import DEFAULT_REASONING_MODE, ReasoningMode

if TYPE_CHECKING:
    # Annotation-only: a runtime import would make studybot.models and
    # studybot.core import each other.
    from studybot.models.base import ModelCapabilities, ModelProvider, ProviderStatus

logger = logging.getLogger(__name__)


def _sanitize_restored(message: Message) -> Message:
    if message.role is not Role.ASSISTANT:
        return message
    cleaned = strip_confident_reasoning(message.content)
    return message if cleaned is message.content else Message.assistant(cleaned)


class ChatService:
    """In-memory conversation history for one chat."""

    def __init__(
        self,
        model: ModelProvider,
        system_prompt: str | None = None,
        history: Sequence[Message] = (),
        reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE,
    ) -> None:
        """``history`` preloads restored user/assistant turns after the system prompt.

        Restored assistant turns pass through ``strip_confident_reasoning``: replies
        saved before reasoning was filtered may contain leaked reasoning, which must
        not be sent back to the model. Only this in-memory copy changes; storage is
        untouched.

        ``reasoning_mode`` is fixed for the instance's lifetime; callers rebuild the
        service to change it.
        """
        self._model = model
        self._reasoning_mode = reasoning_mode
        self._history: list[Message] = []
        if system_prompt:
            self._history.append(Message.system(system_prompt))
        self._history.extend(_sanitize_restored(m) for m in history)

    @property
    def history(self) -> Sequence[Message]:
        """Read-only view of the conversation so far."""
        return tuple(self._history)

    def send(self, user_input: str) -> Message:
        """Add a user message, get the model's response, record it and return it."""
        user_message = Message.user(user_input)
        self._history.append(user_message)
        logger.debug("Sending conversation of length %d to model", len(self._history))

        response = self._model.generate(self._history, reasoning_mode=self._reasoning_mode)

        assistant_message = Message.assistant(response.content)
        self._history.append(assistant_message)
        return assistant_message

    def send_streaming(self, user_input: str) -> Iterator[str]:
        """Like ``send``, but yields the reply incrementally.

        The user message is recorded immediately. The assistant message is added once,
        complete, only after the stream finishes successfully. If the model raises
        partway through, the exception propagates and no assistant message is
        recorded; callers that want the partial text must collect the yielded chunks.
        """
        user_message = Message.user(user_input)
        self._history.append(user_message)
        logger.debug("Streaming conversation of length %d to model", len(self._history))

        chunks: list[str] = []
        for chunk in self._model.stream(self._history, reasoning_mode=self._reasoning_mode):
            chunks.append(chunk)
            yield chunk

        self._history.append(Message.assistant("".join(chunks)))

    def clear(self) -> None:
        """Discard all conversation history for the current session."""
        self._history.clear()
        logger.debug("Chat history cleared")

    def get_status(self) -> ProviderStatus:
        """Check the underlying model provider's current health."""
        return self._model.get_status()

    def get_capabilities(self) -> ModelCapabilities:
        """Return what the model reports it supports (delegates to the provider)."""
        return self._model.get_capabilities()
