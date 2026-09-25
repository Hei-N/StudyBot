"""Chat and course persistence abstractions.

Mirrors the `ModelProvider` pattern in `studybot.models`: everything outside
this package and its concrete implementations talks only to `ChatRepository`
/ `CourseRepository` and their domain types, never to raw SQL or database
rows. A future backend (e.g. an encrypted store, or a sync-capable one) can
replace `SQLiteChatRepository` / `SQLiteCourseRepository` without touching
`SessionService`, `CourseService`, the CLI, or a future GUI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from studybot.core.learning_memory import DEFAULT_MEMORY_STATUS, MemoryKind, MemoryStatus
from studybot.core.messages import Message, Role
from studybot.core.reasoning_mode import DEFAULT_REASONING_MODE, ReasoningMode
from studybot.core.teaching_mode import DEFAULT_TEACHING_MODE, TeachingMode

#: Sentinel distinguishing "don't filter/change this field" from a real
#: value that happens to be `None` (which is itself meaningful — e.g.
#: `course_id=None` means "General"/global). Used by
#: `LearningMemoryRepository.list`/`update`, mirroring the
#: `_KEEP_CURRENT_COURSE` idiom `SessionService` already uses for the same
#: reason.
UNSET = object()


@dataclass(slots=True)
class ChatSession:
    """Metadata for one persisted (or about-to-be-persisted) chat.

    `title` is `None` for a chat that hasn't received its first user message
    yet — the CLI displays this as "Untitled" and `SessionService` fills it
    in automatically once there's something to derive a title from.

    `course_id` is `None` for a "General" chat not associated with any
    course. Course membership is purely organizational: it never merges or
    shares conversation history between chats.

    `teaching_mode` is per-chat (see `core.teaching_mode`): switching a
    chat's mode never affects any other chat, even one in the same course.

    `reasoning_mode` is per-chat too (see `core.reasoning_mode`) and
    entirely independent of `teaching_mode` — one controls instructional
    behavior, the other controls inference depth/latency.
    """

    id: str
    title: str | None
    course_id: str | None
    teaching_mode: TeachingMode
    reasoning_mode: ReasoningMode
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """A persisted message with its stable id and timestamp — distinct from
    `Message` (the plain role/content pair `ChatService`/`ModelProvider`
    exchange). Nothing about LLM context construction needs an id or a
    timestamp, so `Message` stays exactly as it was; `MessageRecord` exists
    purely for callers (the HTTP/WebSocket API) that need to display or
    reference a specific persisted message."""

    id: int
    role: Role
    content: str
    created_at: str


@dataclass(slots=True)
class Course:
    """Metadata for one persisted course. Chats reference it by `id`, but a
    course never holds or aggregates chat history itself."""

    id: str
    name: str
    code: str | None
    term: str | None
    description: str | None
    created_at: str
    updated_at: str


class ChatRepository(Protocol):
    """Durable storage for chats and their messages.

    Implementations must enforce foreign keys (so deleting a chat deletes
    its messages, and deleting a course clears `course_id` on its chats
    without touching the chats themselves), use parameterized SQL only,
    and preserve message insertion order exactly.
    """

    def create_chat(
        self,
        chat_id: str,
        title: str | None,
        course_id: str | None = None,
        teaching_mode: TeachingMode = DEFAULT_TEACHING_MODE,
        reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE,
    ) -> ChatSession:
        """Insert a new chat row and return it (with server-assigned timestamps)."""
        ...

    def get_chat(self, chat_id: str) -> ChatSession | None:
        """Fetch one chat by its exact id, or None if it doesn't exist."""
        ...

    def list_chats(self) -> list[ChatSession]:
        """All chats regardless of course, most recently updated first."""
        ...

    def list_chats_by_course(self, course_id: str | None) -> list[ChatSession]:
        """Chats belonging to one course (or, if `course_id` is None, the
        "General" chats with no course), most recently updated first."""
        ...

    def rename_chat(self, chat_id: str, title: str) -> ChatSession:
        """Set a chat's title and bump its `updated_at`."""
        ...

    def move_chat_to_course(self, chat_id: str, course_id: str | None) -> ChatSession:
        """Reassign a chat's course (None = unassign to General).

        Preserves the chat's id, title, and messages — only `course_id`
        (and `updated_at`) change.
        """
        ...

    def delete_chat(self, chat_id: str) -> None:
        """Delete a chat and (via cascade) all of its messages."""
        ...

    def touch_chat(self, chat_id: str) -> ChatSession:
        """Bump a chat's `updated_at` to now, without changing its title."""
        ...

    def set_teaching_mode(self, chat_id: str, mode: TeachingMode) -> ChatSession:
        """Set a chat's teaching mode and bump its `updated_at`.

        Never touches messages, title, or course — mode is independent of
        all three.
        """
        ...

    def set_reasoning_mode(self, chat_id: str, mode: ReasoningMode) -> ChatSession:
        """Set a chat's reasoning mode and bump its `updated_at`.

        Never touches messages, title, course, or teaching mode — reasoning
        mode is independent of all of them.
        """
        ...

    def append_message(self, chat_id: str, role: Role, content: str) -> None:
        """Persist one message, preserving insertion order for later loads."""
        ...

    def load_messages(self, chat_id: str) -> list[Message]:
        """All persisted user/assistant messages for a chat, in order.

        Never includes a system message — the system prompt (and any course
        context) is application configuration, injected by `ChatService`,
        and is never persisted.
        """
        ...

    def load_message_records(self, chat_id: str) -> list[MessageRecord]:
        """Like `load_messages`, but with each message's stable id and
        timestamp — for callers (the API layer) that need to reference or
        display a specific message, not feed it to a model."""
        ...

    def clear_messages(self, chat_id: str) -> None:
        """Delete all messages for a chat, leaving the chat itself intact."""
        ...

    def count_chats_for_course(self, course_id: str) -> int:
        """How many chats currently belong to a course."""
        ...


@dataclass(slots=True)
class LearningMemory:
    """One durable, course-scoped piece of learning information — separate
    from and independent of chat history (Stage 6). See
    `core.learning_memory` for `MemoryKind`/`MemoryStatus`.

    `course_id` is `None` for genuinely general/global learning
    information — not the common case, but supported (see
    `LearningMemoryService`).

    `source_chat_id` is provenance only: which chat this memory was
    created from, if any. It remains valid (and the memory itself remains
    fully intact) even after that chat is cleared or deleted — see
    `LearningMemoryRepository`'s `ON DELETE SET NULL` foreign key.
    """

    id: str
    course_id: str | None
    source_chat_id: str | None
    topic: str
    kind: MemoryKind
    summary: str
    status: MemoryStatus
    created_at: str
    updated_at: str


class LearningMemoryRepository(Protocol):
    """Durable storage for learning memories.

    Implementations must enforce foreign keys with `ON DELETE SET NULL` on
    both `course_id` (→ `courses.id`) and `source_chat_id` (→ `chats.id`)
    — deleting a course or a chat must never delete a learning memory, only
    clear the now-dangling reference. Archiving (not deleting) is the
    normal way a memory is retired; `delete` is a separate, explicit hard
    delete.
    """

    def create(
        self,
        memory_id: str,
        course_id: str | None,
        source_chat_id: str | None,
        topic: str,
        kind: MemoryKind,
        summary: str,
        status: MemoryStatus = DEFAULT_MEMORY_STATUS,
    ) -> LearningMemory:
        """Insert a new learning memory row and return it (with
        server-assigned timestamps)."""
        ...

    def get(self, memory_id: str) -> LearningMemory | None:
        """Fetch one learning memory by its exact id, or None if it
        doesn't exist."""
        ...

    def list(
        self,
        *,
        course_id: str | None = UNSET,  # type: ignore[assignment]
        kind: MemoryKind | None = None,
        status: MemoryStatus | None = None,
    ) -> list[LearningMemory]:
        """All memories matching the given filters, most recently updated
        first. `course_id=UNSET` (the default) means "any course";
        `course_id=None` means "global memories only"; a real id filters to
        exactly that course. `kind`/`status` of `None` mean "any"."""
        ...

    def update(
        self,
        memory_id: str,
        *,
        course_id: str | None = UNSET,  # type: ignore[assignment]
        topic: str | None = None,
        kind: MemoryKind | None = None,
        summary: str | None = None,
    ) -> LearningMemory:
        """Partially update a memory: only fields that are provided
        change. `course_id=UNSET` (the default) leaves it unchanged;
        `course_id=None` explicitly unassigns it to General/global.
        `topic`/`kind`/`summary` of `None` mean "leave unchanged" (a real
        value can never legitimately be `None` once validated)."""
        ...

    def archive(self, memory_id: str) -> LearningMemory:
        """Set a memory's status to archived and bump `updated_at`."""
        ...

    def restore(self, memory_id: str) -> LearningMemory:
        """Set a memory's status back to active and bump `updated_at`."""
        ...

    def delete(self, memory_id: str) -> None:
        """Permanently delete a memory. An explicit, separate operation
        from `archive` — normal retirement should archive, not delete."""
        ...

    def archive_for_course(self, course_id: str) -> None:
        """Archive every currently *active* memory belonging to
        `course_id` (Stage 6.1). Used by `CourseService.delete_course` so a
        course's memories are retired, not silently turned into active
        global memories, when their course goes away — see that method's
        docstring for the full policy. Never touches memories that are
        already archived, or memories belonging to a different course (or
        no course at all)."""
        ...


class CourseRepository(Protocol):
    """Durable storage for course metadata (not chats — see `ChatRepository`)."""

    def create_course(
        self, course_id: str, name: str, code: str | None, term: str | None, description: str | None
    ) -> Course:
        """Insert a new course row and return it (with server-assigned timestamps)."""
        ...

    def get_course(self, course_id: str) -> Course | None:
        """Fetch one course by its exact id, or None if it doesn't exist."""
        ...

    def list_courses(self) -> list[Course]:
        """All courses, most recently *edited* first (chat activity within a
        course never bumps the course's own `updated_at`)."""
        ...

    def update_course(
        self, course_id: str, name: str, code: str | None, term: str | None, description: str | None
    ) -> Course:
        """Fully replace a course's editable fields and bump its `updated_at`."""
        ...

    def delete_course(self, course_id: str) -> None:
        """Delete a course. Its chats and their messages are preserved —
        implementations must use ON DELETE SET NULL on `chats.course_id`,
        never cascade a course deletion into its chats."""
        ...
