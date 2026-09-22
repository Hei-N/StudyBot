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

Course awareness (Stage 4) works the same way: `SessionService` reads
`CourseRepository` (never writes to it — that's `CourseService`'s job) only
to build the minimal `CourseContext` for whichever course the active chat
belongs to, and feeds it through `core.context.build_system_prompt` whenever
`ChatService` is (re)built. `ChatService`/`ModelProvider` never see a course
or a `CourseContext` — only the resulting system-prompt text.

Teaching mode (Stage 5) is simpler still: it's a plain field on the active
`ChatSession`, fed into the same `build_system_prompt` call as another
independent section. Changing it never touches messages, title, or course,
and — like course context — it's never persisted as a chat message.

Reasoning mode (Stage 5.7) is a second, independent plain field on
`ChatSession` — unlike teaching mode it never feeds into the system prompt
at all; it's passed straight through to `ChatService`/`ModelProvider` as an
inference-time preference (see `core.reasoning_mode`), since it controls
*how* the model answers (thinking depth/latency), not *what instructions*
it's given.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Iterator, Sequence

from studybot.core.chat import ChatService
from studybot.core.context import CourseContext, build_system_prompt
from studybot.core.exceptions import SessionError
from studybot.core.messages import Message, Role
from studybot.core.mode_prompts import get_mode_prompt
from studybot.core.reasoning_mode import DEFAULT_REASONING_MODE, ReasoningMode
from studybot.core.teaching_mode import DEFAULT_TEACHING_MODE, TeachingMode
from studybot.core.titles import generate_title
from studybot.models.base import ModelProvider, ProviderStatus
from studybot.storage.base import ChatRepository, ChatSession, Course, CourseRepository, MessageRecord

logger = logging.getLogger(__name__)

_KEEP_CURRENT_COURSE = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionService:
    """Owns the active chat and keeps it mirrored to persistent storage."""

    def __init__(
        self,
        model: ModelProvider,
        repository: ChatRepository,
        course_repository: CourseRepository,
        system_prompt: str | None = None,
    ) -> None:
        self._model = model
        self._repository = repository
        self._course_repository = course_repository
        self._baseline_system_prompt = system_prompt
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
        """A chat that exists only in memory until its first message arrives.

        This avoids writing an empty "Untitled" row every time the app is
        launched (or a course opened) and quit without anyone actually
        chatting. Always starts in the default teaching mode (Teach) and
        the default reasoning mode (Fast) — a new chat never inherits
        whatever mode was active elsewhere.
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
        """Create and switch to a fresh, empty chat.

        With no argument, the new chat stays in whatever course context (or
        General) was already active — this is what a bare `/new` uses. Pass
        an explicit course id (or `None` for General) to target a specific
        course regardless of what's currently active.
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
        """Look up one chat's metadata without switching the active chat.

        A stateless read, unlike `open_chat` — for callers (the API layer)
        that need one chat's data by explicit id without disturbing
        whatever chat is currently active in this process.
        """
        return self._repository.get_chat(chat_id)

    def get_chat_history_records(self, chat_id: str) -> list[MessageRecord]:
        """Like `get_chat`: a stateless read of one chat's persisted
        messages (with stable ids/timestamps) by explicit id, without
        switching the active chat."""
        return self._repository.load_message_records(chat_id)

    def open_chat(self, id_or_prefix: str) -> ChatSession:
        """Switch to an existing chat by exact id or unambiguous id prefix."""
        session = self._resolve_chat(id_or_prefix)
        self._load_chat(session)
        return session

    def open_course_context(self, course_id: str | None) -> ChatSession:
        """Activate a course's context: resume its most recently updated
        chat if it has one, otherwise start an empty chat scoped to it
        without writing a meaningless row just for viewing the course.

        `course_id=None` means "General" — used by `/course leave` too.
        """
        chats = self._repository.list_chats_by_course(course_id)
        if chats:
            self._load_chat(chats[0])
        else:
            self._start_new_chat_in_memory(course_id)
        return self._active_session

    def move_active_chat_to_course(self, id_or_prefix: str | None) -> ChatSession:
        """Reassign the active chat to a course (`None` = unassign to
        General), preserving its id, title, mode, and messages."""
        course_id = None
        if id_or_prefix is not None:
            course_id = self._resolve_course(id_or_prefix).id

        if self._active_persisted:
            self._active_session = self._repository.move_chat_to_course(
                self._active_session.id, course_id
            )
        else:
            self._active_session.course_id = course_id

        self._rebuild_chat_service_preserving_history()
        return self._active_session

    def sync_active_chat_course(self) -> ChatSession:
        """Re-read the active chat's course from storage and refresh the
        in-memory system prompt to match, without switching chats.

        Needed after a course is deleted out from under the active chat:
        the database's ON DELETE SET NULL already cleared `course_id`
        there, but the in-memory `ChatService` still has the old course's
        context baked into its system prompt until this runs.
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
        title = " ".join(title.split())
        if not title:
            raise SessionError("A chat title cannot be empty.")

        if self._active_persisted:
            self._active_session = self._repository.rename_chat(self._active_session.id, title)
        else:
            self._active_session.title = title
        return self._active_session

    def delete_active_chat(self) -> ChatSession:
        """Delete the active chat, then activate another.

        Prefers another chat within the same course if one remains; if the
        chat was in a course that now has none left, starts a fresh empty
        chat scoped to that same course rather than jumping to an unrelated
        one. Only a General (course-less) chat falls back to the plain
        most-recently-updated-overall behavior from Stage 3.
        """
        deleted = self._active_session
        course_id = deleted.course_id
        if self._active_persisted:
            self._repository.delete_chat(deleted.id)

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
        """Remove the active chat's messages; the chat itself is kept.

        The next model request still receives the configured system
        prompt (course context and teaching mode, if any) — only persisted
        user/assistant turns are removed.
        """
        if self._active_persisted:
            self._repository.clear_messages(self._active_session.id)
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

        Persists immediately, never touches messages/title/course, and
        applies starting with the next model request — no confirmation
        message is (or should be) added to conversation history for this.
        """
        if self._active_persisted:
            self._active_session = self._repository.set_teaching_mode(self._active_session.id, mode)
        else:
            self._active_session.teaching_mode = mode
        self._rebuild_chat_service_preserving_history()
        return self._active_session

    # --- reasoning mode --------------------------------------------------------

    def get_reasoning_mode(self) -> ReasoningMode:
        return self._active_session.reasoning_mode

    def set_reasoning_mode(self, mode: ReasoningMode) -> ChatSession:
        """Change the active chat's reasoning mode.

        Persists immediately, never touches messages/title/course/teaching
        mode, and applies starting with the next model request — like
        teaching mode, no confirmation message is added to conversation
        history for this.
        """
        if self._active_persisted:
            self._active_session = self._repository.set_reasoning_mode(self._active_session.id, mode)
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

    # --- internal --------------------------------------------------------------

    def _effective_system_prompt(self, course_id: str | None, teaching_mode: TeachingMode) -> str | None:
        context = self._course_context(course_id)
        mode_instructions = get_mode_prompt(teaching_mode)
        prompt = build_system_prompt(self._baseline_system_prompt or "", context, mode_instructions)
        return prompt if prompt.strip() else None

    def _course_context(self, course_id: str | None) -> CourseContext | None:
        if course_id is None:
            return None
        course = self._course_repository.get_course(course_id)
        if course is None:
            # The course was deleted concurrently; treat as General rather
            # than erroring — `sync_active_chat_course` is what normally
            # catches this up explicitly.
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

        for message in messages:
            self._repository.append_message(self._active_session.id, message.role, message.content)
            if message.role is Role.USER and self._active_session.title is None:
                title = generate_title(message.content)
                self._active_session = self._repository.rename_chat(self._active_session.id, title)

        self._active_session = self._repository.touch_chat(self._active_session.id)
