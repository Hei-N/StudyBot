"""Chat service: the core conversation logic, independent of any UI or backend.

Interfaces (CLI, future desktop UI, future macOS assistant) call into this
service. The service in turn calls a `ModelProvider`. Neither this module nor
its callers should know which concrete model backend is in use.
"""

from __future__ import annotations

import logging
from typing import Iterator, Sequence

from studybot.core.messages import Message, Role
from studybot.core.output_integrity import strip_confident_reasoning
from studybot.core.reasoning_mode import DEFAULT_REASONING_MODE, ReasoningMode
from studybot.models.base import ModelProvider, ProviderStatus

logger = logging.getLogger(__name__)


def _sanitize_restored(message: Message) -> Message:
    if message.role is not Role.ASSISTANT:
        return message
    cleaned = strip_confident_reasoning(message.content)
    return message if cleaned is message.content else Message.assistant(cleaned)


class ChatService:
    """Manages in-memory conversation history for a single session."""

    def __init__(
        self,
        model: ModelProvider,
        system_prompt: str | None = None,
        history: Sequence[Message] = (),
        reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE,
    ) -> None:
        """`history` preloads prior user/assistant turns (e.g. restored from
        persistence) after the system prompt, without re-sending it to the
        model until the next `send`/`send_streaming` call.

        Assistant turns in `history` are passed through
        `strip_confident_reasoning` first (Stage 6.3): a reply persisted
        before reasoning was separated at the provider boundary may still
        hold the model's leaked chain-of-thought, which must not be fed
        back to the model as if the assistant had said it. Storage is never
        touched — only this in-memory copy — and a reply is only changed
        when the reasoning portion is identified with confidence.

        `reasoning_mode` is fixed for this service instance's lifetime, like
        `system_prompt` — callers (`SessionService`) that need to change it
        for an existing chat rebuild the `ChatService`, the same way they
        already do when teaching mode changes.
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
        """Add a user message, get a model response, and record it.

        Returns the assistant's reply message.
        """
        user_message = Message.user(user_input)
        self._history.append(user_message)
        logger.debug("Sending conversation of length %d to model", len(self._history))

        response = self._model.generate(self._history, reasoning_mode=self._reasoning_mode)

        assistant_message = Message.assistant(response.content)
        self._history.append(assistant_message)
        return assistant_message

    def send_streaming(self, user_input: str) -> Iterator[str]:
        """Like `send`, but yields response content incrementally.

        The user message is recorded immediately. The assistant's reply is
        accumulated from the yielded chunks and recorded as a single,
        complete message in history only after the stream finishes
        successfully — history never ends up holding a partial reply.

        If the underlying model raises partway through, the exception
        propagates to the caller and NO assistant message is added: the
        conversation is left with the user's message but no (necessarily
        incomplete or misleading) reply, rather than silently recording a
        truncated response as if it were complete. Callers that need to
        show the caller how much text arrived before the failure should
        collect the chunks yielded before the exception themselves.
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
