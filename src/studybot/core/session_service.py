"""Chat/session orchestration on top of ChatService and the repositories.

Two layers share the same storage:

* Active-chat layer (``new_chat``, ``open_chat``, ``send``, ...): one mutable
  "current chat" per process, used by the CLI. A new chat stays in memory
  until its first message, so launching and quitting writes nothing.
* Explicit layer (``create_chat``, ``send_to_chat``, ``*_for_chat``, ...):
  every method takes a ``chat_id`` and loads that chat from the repository,
  so operations on different chats cannot interfere. The API uses this layer.
  A per-chat lock rejects overlapping generations for the same chat.

Messages are persisted by diffing ``ChatService.history`` before and after
each model call, so a failed or abandoned stream saves only the user message.
The system prompt combines the baseline prompt, course context, learning
memory and teaching mode; reasoning mode is passed through to the model.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Iterator, Sequence

from studybot.core.chat import ChatService
from studybot.core.context import CourseContext, build_system_prompt
from studybot.core.exceptions import ChatBusyError, ChatNotFoundError, SessionError
from studybot.core.memory_service import LearningMemoryService
from studybot.core.messages import Message, Role
from studybot.core.mode_prompts import get_mode_prompt
from studybot.core.reasoning_mode import DEFAULT_REASONING_MODE, ReasoningMode
from studybot.core.teaching_mode import DEFAULT_TEACHING_MODE, TeachingMode
from studybot.core.titles import generate_title
from studybot.models.base import ModelCapabilities, ModelProvider, ProviderStatus
from studybot.storage.base import ChatRepository, ChatSession, Course, CourseRepository, MessageRecord

logger = logging.getLogger(__name__)

_KEEP_CURRENT_COURSE = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionService:
    """Owns the active chat and mirrors it to persistent storage."""

    def __init__(
        self,
        model: ModelProvider,
        repository: ChatRepository,
        course_repository: CourseRepository,
        system_prompt: str | None = None,
        memory_service: LearningMemoryService | None = None,
    ) -> None:
        self._model = model
        self._repository = repository
        self._course_repository = course_repository
        self._baseline_system_prompt = system_prompt
        # Optional: without it, no learning-memory context is injected.
        self._memory_service = memory_service
        self._active_session: ChatSession
        self._active_persisted: bool
        self._chat: ChatService
        self._activate_most_recent_or_new()
        # Per-chat generation locks for the explicit layer. The guard only
        # protects creation of lock entries.
        self._chat_locks: dict[str, threading.Lock] = {}
        self._chat_locks_guard = threading.Lock()

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
            self._start_new_chat_in_memory(None)

    def _load_chat(self, session: ChatSession) -> None:
        messages = self._repository.load_messages(session.id)
        self._active_session = session
        self._active_persisted = True
        self._chat = ChatService(
            model=self._model,
            system_prompt=self._effective_system_prompt(session.course_id, session.teaching_mode),
            history=messages,
            reasoning_mode=session.reasoning_mode,
        )

    def _start_new_chat_in_memory(self, course_id: str | None) -> None:
        """Start an unpersisted chat in the default teaching and reasoning modes.

        The database row is created on the first message.
        """
        now = _now()
        self._active_session = ChatSession(
            id=str(uuid.uuid4()),
            title=None,
            course_id=course_id,
            teaching_mode=DEFAULT_TEACHING_MODE,
            reasoning_mode=DEFAULT_REASONING_MODE,
            created_at=now,
            updated_at=now,
        )
        self._active_persisted = False
        self._chat = ChatService(
            model=self._model,
            system_prompt=self._effective_system_prompt(course_id, DEFAULT_TEACHING_MODE),
            reasoning_mode=DEFAULT_REASONING_MODE,
        )

    # --- chat lifecycle ------------------------------------------------------

    def new_chat(self, course_id=_KEEP_CURRENT_COURSE) -> ChatSession:
        """Switch to a fresh, empty chat.

        Stays in the active course by default; pass a course id (or None for
        General) to override.
        """
        if course_id is _KEEP_CURRENT_COURSE:
            course_id = self._active_session.course_id
        self._start_new_chat_in_memory(course_id)
        return self._active_session

    def list_chats(self) -> list[ChatSession]:
        return self._repository.list_chats()

    def list_chats_in_course(self, course_id: str | None) -> list[ChatSession]:
        return self._repository.list_chats_by_course(course_id)

    def get_chat(self, chat_id: str) -> ChatSession | None:
        """Return one chat's metadata without changing the active chat."""
        return self._repository.get_chat(chat_id)

    def get_chat_history_records(self, chat_id: str) -> list[MessageRecord]:
        """Return one chat's persisted messages (with ids and timestamps) without
        changing the active chat.
        """
        return self._repository.load_message_records(chat_id)

    def open_chat(self, id_or_prefix: str) -> ChatSession:
        """Switch to an existing chat by exact id or unambiguous id prefix."""
        session = self._resolve_chat(id_or_prefix)
        self._load_chat(session)
        return session

    def open_course_context(self, course_id: str | None) -> ChatSession:
        """Resume the course's most recently updated chat, or start an empty
        in-memory chat for it. ``None`` means General.
        """
        chats = self._repository.list_chats_by_course(course_id)
        if chats:
            self._load_chat(chats[0])
        else:
            self._start_new_chat_in_memory(course_id)
        return self._active_session

    def move_active_chat_to_course(self, id_or_prefix: str | None) -> ChatSession:
        """Reassign the active chat to a course (None = General), keeping its id,
        title, mode and messages.
        """
        course_id = None
        if id_or_prefix is not None:
            course_id = self._resolve_course(id_or_prefix).id

        if self._active_persisted:
            self._active_session = self.assign_course_to_chat(self._active_session.id, course_id)
        else:
            self._active_session.course_id = course_id

        self._rebuild_chat_service_preserving_history()
        return self._active_session

    def sync_active_chat_course(self) -> ChatSession:
        """Reload the active chat's course and rebuild its system prompt.

        Needed after a course is deleted: the database clears ``course_id``, but the
        in-memory prompt still carries the old course context.
        """
        if self._active_persisted:
            refreshed = self._repository.get_chat(self._active_session.id)
            if refreshed is not None:
                self._active_session = refreshed
        self._rebuild_chat_service_preserving_history()
        return self._active_session

    def _rebuild_chat_service_preserving_history(self) -> None:
        history = [m for m in self._chat.history if m.role is not Role.SYSTEM]
        self._chat = ChatService(
            model=self._model,
            system_prompt=self._effective_system_prompt(
                self._active_session.course_id, self._active_session.teaching_mode
            ),
            history=history,
            reasoning_mode=self._active_session.reasoning_mode,
        )

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

    def _resolve_course(self, id_or_prefix: str) -> Course:
        courses = self._course_repository.list_courses()

        exact = next((c for c in courses if c.id == id_or_prefix), None)
        if exact is not None:
            return exact

        matches = [c for c in courses if c.id.startswith(id_or_prefix)]
        if not matches:
            raise SessionError(f"No course found matching '{id_or_prefix}'.")
        if len(matches) > 1:
            raise SessionError(f"'{id_or_prefix}' matches {len(matches)} courses; use a longer id.")
        return matches[0]

    def rename_active_chat(self, title: str) -> ChatSession:
        if self._active_persisted:
            self._active_session = self.rename_chat(self._active_session.id, title)
        else:
            title = " ".join(title.split())
            if not title:
                raise SessionError("A chat title cannot be empty.")
            self._active_session.title = title
        return self._active_session

    def delete_active_chat(self) -> ChatSession:
        """Delete the active chat and activate another.

        Prefers a chat in the same course, otherwise starts an empty chat in that
        course. From General, falls back to the most recently updated chat.
        """
        deleted = self._active_session
        course_id = deleted.course_id
        if self._active_persisted:
            self.delete_chat(deleted.id)

        if course_id is not None:
            remaining = self._repository.list_chats_by_course(course_id)
            if remaining:
                self._load_chat(remaining[0])
            else:
                self._start_new_chat_in_memory(course_id)
        else:
            self._activate_most_recent_or_new()

        return deleted

    def clear_active_chat(self) -> None:
        """Remove the active chat's messages but keep the chat.

        The course and teaching-mode prompt still applies to the next request.
        """
        if self._active_persisted:
            self.clear_chat(self._active_session.id)
        self._chat = ChatService(
            model=self._model,
            system_prompt=self._effective_system_prompt(
                self._active_session.course_id, self._active_session.teaching_mode
            ),
            reasoning_mode=self._active_session.reasoning_mode,
        )

    # --- teaching mode -------------------------------------------------------

    def get_teaching_mode(self) -> TeachingMode:
        return self._active_session.teaching_mode

    def set_teaching_mode(self, mode: TeachingMode) -> ChatSession:
        """Change the active chat's teaching mode.

        Persisted immediately; applies from the next request and adds no message to
        the history.
        """
        if self._active_persisted:
            self._active_session = self.set_teaching_mode_for_chat(self._active_session.id, mode)
        else:
            self._active_session.teaching_mode = mode
        self._rebuild_chat_service_preserving_history()
        return self._active_session

    # --- reasoning mode --------------------------------------------------------

    def get_reasoning_mode(self) -> ReasoningMode:
        return self._active_session.reasoning_mode

    def set_reasoning_mode(self, mode: ReasoningMode) -> ChatSession:
        """Change the active chat's reasoning mode.

        Persisted immediately; applies from the next request and adds no message to
        the history.
        """
        if self._active_persisted:
            self._active_session = self.set_reasoning_mode_for_chat(self._active_session.id, mode)
        else:
            self._active_session.reasoning_mode = mode
        self._rebuild_chat_service_preserving_history()
        return self._active_session

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

    def get_model_capabilities(self) -> ModelCapabilities:
        """Return the model's reported capabilities.

        Read-only: does not touch chat state.
        """
        return self._chat.get_capabilities()

    # --- internal --------------------------------------------------------------

    def _effective_system_prompt(self, course_id: str | None, teaching_mode: TeachingMode) -> str | None:
        context = self._course_context(course_id)
        mode_instructions = get_mode_prompt(teaching_mode)
        memory_context = self._memory_service.build_memory_context_text(course_id) if self._memory_service else None
        prompt = build_system_prompt(
            self._baseline_system_prompt or "", context, mode_instructions, memory_context=memory_context
        )
        return prompt if prompt.strip() else None

    def _course_context(self, course_id: str | None) -> CourseContext | None:
        if course_id is None:
            return None
        course = self._course_repository.get_course(course_id)
        if course is None:
            # Deleted concurrently: treat as General.
            return None
        return CourseContext(name=course.name, code=course.code, term=course.term, description=course.description)

    def _persist_new_messages(self, messages: Sequence[Message]) -> None:
        if not messages:
            return

        if not self._active_persisted:
            self._active_session = self._repository.create_chat(
                self._active_session.id,
                self._active_session.title,
                self._active_session.course_id,
                self._active_session.teaching_mode,
                self._active_session.reasoning_mode,
            )
            self._active_persisted = True

        self._active_session = self._persist_new_messages_for(
            self._active_session.id, self._active_session, messages
        )

    def _persist_new_messages_for(
        self, chat_id: str, session: ChatSession, messages: Sequence[Message]
    ) -> ChatSession:
        """Append messages to a persisted chat, titling it from the first user
        message if it has no title yet.
        """
        if not messages:
            return session

        for message in messages:
            self._repository.append_message(chat_id, message.role, message.content)
            if message.role is Role.USER and session.title is None:
                session = self._repository.rename_chat(chat_id, generate_title(message.content))

        return self._repository.touch_chat(chat_id)

    def _require_chat(self, chat_id: str) -> ChatSession:
        session = self._repository.get_chat(chat_id)
        if session is None:
            raise ChatNotFoundError(f"No chat found with id '{chat_id}'.")
        return session

    def _chat_lock(self, chat_id: str) -> threading.Lock:
        with self._chat_locks_guard:
            lock = self._chat_locks.get(chat_id)
            if lock is None:
                lock = threading.Lock()
                self._chat_locks[chat_id] = lock
            return lock

    # --- explicit chat-id operations ---------------------------------------------
    # Each method takes a chat_id and loads that chat from the repository;
    # none uses the active-chat cursor.

    def create_chat(self, course_id: str | None = None) -> ChatSession:
        """Create and persist an empty chat immediately (API-facing).

        Unlike ``new_chat``, the row exists right away so the chat can be addressed
        before its first message. Does not touch the active-chat cursor; the caller
        validates the course.
        """
        chat_id = str(uuid.uuid4())
        return self._repository.create_chat(chat_id, None, course_id, DEFAULT_TEACHING_MODE, DEFAULT_REASONING_MODE)

    def get_chat_history(self, chat_id: str) -> list[Message]:
        """Return the chat's model-ready history (no system message)."""
        self._require_chat(chat_id)
        return self._repository.load_messages(chat_id)

    def rename_chat(self, chat_id: str, title: str) -> ChatSession:
        self._require_chat(chat_id)
        title = " ".join(title.split())
        if not title:
            raise SessionError("A chat title cannot be empty.")
        return self._repository.rename_chat(chat_id, title)

    def clear_chat(self, chat_id: str) -> ChatSession:
        """Delete a chat's messages; the chat itself is kept."""
        session = self._require_chat(chat_id)
        self._repository.clear_messages(chat_id)
        return session

    def delete_chat(self, chat_id: str) -> ChatSession:
        """Delete a chat by id. Does not activate a replacement."""
        session = self._require_chat(chat_id)
        self._repository.delete_chat(chat_id)
        return session

    def assign_course_to_chat(self, chat_id: str, course_id: str | None) -> ChatSession:
        """Move a chat to a course by exact id (None = General)."""
        self._require_chat(chat_id)
        if course_id is not None and self._course_repository.get_course(course_id) is None:
            raise SessionError(f"No course found with id '{course_id}'.")
        return self._repository.move_chat_to_course(chat_id, course_id)

    def set_teaching_mode_for_chat(self, chat_id: str, mode: TeachingMode) -> ChatSession:
        self._require_chat(chat_id)
        return self._repository.set_teaching_mode(chat_id, mode)

    def set_reasoning_mode_for_chat(self, chat_id: str, mode: ReasoningMode) -> ChatSession:
        self._require_chat(chat_id)
        return self._repository.set_reasoning_mode(chat_id, mode)

    def send_to_chat(self, chat_id: str, user_input: str) -> Message:
        """Send a message to a persisted chat and return the reply.

        Builds a fresh ChatService from that chat's own history and settings.
        Raises ChatBusyError if a generation for the same chat is already running.
        """
        session = self._require_chat(chat_id)
        lock = self._chat_lock(chat_id)
        if not lock.acquire(blocking=False):
            raise ChatBusyError(f"Chat '{chat_id}' already has a generation in progress.")
        try:
            history = self._repository.load_messages(chat_id)
            chat = ChatService(
                model=self._model,
                system_prompt=self._effective_system_prompt(session.course_id, session.teaching_mode),
                history=history,
                reasoning_mode=session.reasoning_mode,
            )
            before = len(chat.history)
            reply = chat.send(user_input)
            self._persist_new_messages_for(chat_id, session, chat.history[before:])
            return reply
        finally:
            lock.release()

    def send_streaming_to_chat(self, chat_id: str, user_input: str) -> Iterator[str]:
        """Streaming variant of ``send_to_chat``.

        The chat is resolved and its lock acquired on the first ``next()``. The lock
        is released when the stream completes, fails or is closed.
        """
        session = self._require_chat(chat_id)
        lock = self._chat_lock(chat_id)
        if not lock.acquire(blocking=False):
            raise ChatBusyError(f"Chat '{chat_id}' already has a generation in progress.")
        try:
            history = self._repository.load_messages(chat_id)
            chat = ChatService(
                model=self._model,
                system_prompt=self._effective_system_prompt(session.course_id, session.teaching_mode),
                history=history,
                reasoning_mode=session.reasoning_mode,
            )
            before = len(chat.history)
            try:
                yield from chat.send_streaming(user_input)
            finally:
                self._persist_new_messages_for(chat_id, session, chat.history[before:])
        finally:
            lock.release()
