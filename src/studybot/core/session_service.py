"""Session service: multiple persisted chats layered on top of `ChatService`.

This is the orchestration point between the model-inference path
(`ChatService` → `ModelProvider`) and the persistence path (`ChatRepository`
→ `SQLiteChatRepository`) — see the module docstrings on those two for why
neither side knows the other exists. `SessionService` is what `StudyBotApp`
(and therefore the CLI, and later a GUI) actually talks to for chat/session
behavior.

Write-through persistence works by diffing `ChatService.history` before and
after each model call rather than teaching `ChatService` about storage: the
existing Stage 2 guarantee ("exactly one assistant message is added to
history, and only after a stream completes successfully; a failure or
early abandonment leaves just the user message") is reused as-is — whatever
new messages appear in `ChatService.history` are exactly what gets persisted.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Iterator, Sequence

from studybot.core.chat import ChatService
from studybot.core.exceptions import SessionError
from studybot.core.messages import Message, Role
from studybot.core.titles import generate_title
from studybot.models.base import ModelProvider, ProviderStatus
from studybot.storage.base import ChatRepository, ChatSession

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionService:
    """Owns the active chat and keeps it mirrored to persistent storage."""

    def __init__(
        self,
        model: ModelProvider,
        repository: ChatRepository,
        system_prompt: str | None = None,
    ) -> None:
        self._model = model
        self._repository = repository
        self._system_prompt = system_prompt
        self._active_session: ChatSession
        self._active_persisted: bool
        self._chat: ChatService
        self._activate_most_recent_or_new()

    # --- active chat -------------------------------------------------------

    @property
    def active_session(self) -> ChatSession:
        return self._active_session

    @property
    def history(self) -> Sequence[Message]:
        return self._chat.history

    def _activate_most_recent_or_new(self) -> None:
        chats = self._repository.list_chats()
        if chats:
            self._load_chat(chats[0])
        else:
            self._start_new_chat_in_memory()

    def _load_chat(self, session: ChatSession) -> None:
        messages = self._repository.load_messages(session.id)
        self._active_session = session
        self._active_persisted = True
        self._chat = ChatService(model=self._model, system_prompt=self._system_prompt, history=messages)

    def _start_new_chat_in_memory(self) -> None:
        """A chat that exists only in memory until its first message arrives.

        This avoids writing an empty "Untitled" row every time the app is
        launched and quit without anyone actually chatting.
        """
        now = _now()
        self._active_session = ChatSession(id=str(uuid.uuid4()), title=None, created_at=now, updated_at=now)
        self._active_persisted = False
        self._chat = ChatService(model=self._model, system_prompt=self._system_prompt)

    # --- chat lifecycle ------------------------------------------------------

    def new_chat(self) -> ChatSession:
        """Create and switch to a fresh, empty chat."""
        self._start_new_chat_in_memory()
        return self._active_session

    def list_chats(self) -> list[ChatSession]:
        return self._repository.list_chats()

    def open_chat(self, id_or_prefix: str) -> ChatSession:
        """Switch to an existing chat by exact id or unambiguous id prefix."""
        session = self._resolve_chat(id_or_prefix)
        self._load_chat(session)
        return session

    def _resolve_chat(self, id_or_prefix: str) -> ChatSession:
        chats = self._repository.list_chats()

        exact = next((c for c in chats if c.id == id_or_prefix), None)
        if exact is not None:
            return exact

        matches = [c for c in chats if c.id.startswith(id_or_prefix)]
        if not matches:
            raise SessionError(f"No chat found matching '{id_or_prefix}'.")
        if len(matches) > 1:
            raise SessionError(
                f"'{id_or_prefix}' matches {len(matches)} chats; use a longer id."
            )
        return matches[0]

    def rename_active_chat(self, title: str) -> ChatSession:
        title = " ".join(title.split())
        if not title:
            raise SessionError("A chat title cannot be empty.")

        if self._active_persisted:
            self._active_session = self._repository.rename_chat(self._active_session.id, title)
        else:
            self._active_session.title = title
        return self._active_session

    def delete_active_chat(self) -> ChatSession:
        """Delete the active chat, then activate another (or a fresh one)."""
        deleted = self._active_session
        if self._active_persisted:
            self._repository.delete_chat(deleted.id)
        self._activate_most_recent_or_new()
        return deleted

    def clear_active_chat(self) -> None:
        """Remove the active chat's messages; the chat itself is kept.

        The next model request still receives the configured system
        prompt — only persisted user/assistant turns are removed.
        """
        if self._active_persisted:
            self._repository.clear_messages(self._active_session.id)
        self._chat = ChatService(model=self._model, system_prompt=self._system_prompt)

    # --- model interaction with write-through persistence ---------------------

    def send(self, user_input: str) -> Message:
        before = len(self._chat.history)
        try:
            return self._chat.send(user_input)
        finally:
            self._persist_new_messages(self._chat.history[before:])

    def send_streaming(self, user_input: str) -> Iterator[str]:
        before = len(self._chat.history)
        try:
            yield from self._chat.send_streaming(user_input)
        finally:
            self._persist_new_messages(self._chat.history[before:])

    def get_status(self) -> ProviderStatus:
        return self._chat.get_status()

    # --- internal --------------------------------------------------------------

    def _persist_new_messages(self, messages: Sequence[Message]) -> None:
        if not messages:
            return

        if not self._active_persisted:
            self._active_session = self._repository.create_chat(
                self._active_session.id, self._active_session.title
            )
            self._active_persisted = True

        for message in messages:
            self._repository.append_message(self._active_session.id, message.role, message.content)
            if message.role is Role.USER and self._active_session.title is None:
                title = generate_title(message.content)
                self._active_session = self._repository.rename_chat(self._active_session.id, title)

        self._active_session = self._repository.touch_chat(self._active_session.id)
