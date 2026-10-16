"""Persistence interfaces and domain types for chats, courses, learning memories and the study library.

Code outside ``studybot.storage`` talks only to these protocols and never sees
SQL or database rows, so a backend can be replaced without touching the
services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from studybot.core.learning_memory import DEFAULT_MEMORY_STATUS, MemoryKind, MemoryStatus
from studybot.core.library import LibraryFileState, LibrarySourceKind
from studybot.core.messages import Message, Role
from studybot.core.reasoning_mode import DEFAULT_REASONING_MODE, ReasoningMode
from studybot.core.teaching_mode import DEFAULT_TEACHING_MODE, TeachingMode

#: Sentinel for "don't filter or change this field", distinct from ``None``
#: (which means General/global).
UNSET = object()


@dataclass(slots=True)
class ChatSession:
    """Metadata for one chat.

    ``title`` is None until the first user message. ``course_id`` is None for a
    "General" chat; course membership is organizational only and never shares
    history between chats. ``teaching_mode`` and ``reasoning_mode`` are per chat
    and independent of each other.
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
    """A persisted message with its id and timestamp.

    For callers (the API) that need to reference a specific message; ``Message``
    stays a plain role/content pair.
    """

    id: int
    role: Role
    content: str
    created_at: str


@dataclass(slots=True)
class Course:
    """Metadata for one course. Chats reference it by ``id``; a course holds no chat history."""

    id: str
    name: str
    code: str | None
    term: str | None
    description: str | None
    created_at: str
    updated_at: str


class ChatRepository(Protocol):
    """Durable storage for chats and messages.

    Implementations must enforce foreign keys (deleting a chat deletes its
    messages; deleting a course clears ``course_id`` on its chats), use
    parameterized SQL, and preserve message order.
    """

    def create_chat(
        self,
        chat_id: str,
        title: str | None,
        course_id: str | None = None,
        teaching_mode: TeachingMode = DEFAULT_TEACHING_MODE,
        reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE,
    ) -> ChatSession:
        """Insert a chat and return it with its assigned timestamps."""
        ...

    def get_chat(self, chat_id: str) -> ChatSession | None:
        """Return a chat by exact id, or None."""
        ...

    def list_chats(self) -> list[ChatSession]:
        """All chats, most recently updated first."""
        ...

    def list_chats_by_course(self, course_id: str | None) -> list[ChatSession]:
        """Chats in a course (or General chats if ``course_id`` is None), most recently
        updated first.
        """
        ...

    def rename_chat(self, chat_id: str, title: str) -> ChatSession:
        """Set a chat's title and bump its `updated_at`."""
        ...

    def move_chat_to_course(self, chat_id: str, course_id: str | None) -> ChatSession:
        """Reassign a chat's course (None = General).

        Only ``course_id`` and ``updated_at`` change.
        """
        ...

    def delete_chat(self, chat_id: str) -> None:
        """Delete a chat and, by cascade, its messages."""
        ...

    def touch_chat(self, chat_id: str) -> ChatSession:
        """Bump a chat's `updated_at` to now, without changing its title."""
        ...

    def set_teaching_mode(self, chat_id: str, mode: TeachingMode) -> ChatSession:
        """Set a chat's teaching mode and bump ``updated_at``.

        Messages, title and course are untouched.
        """
        ...

    def set_reasoning_mode(self, chat_id: str, mode: ReasoningMode) -> ChatSession:
        """Set a chat's reasoning mode and bump ``updated_at``.

        Messages, title, course and teaching mode are untouched.
        """
        ...

    def append_message(self, chat_id: str, role: Role, content: str) -> None:
        """Persist one message in insertion order."""
        ...

    def load_messages(self, chat_id: str) -> list[Message]:
        """Return a chat's user/assistant messages in order.

        The system prompt is never persisted, so it is never included.
        """
        ...

    def load_message_records(self, chat_id: str) -> list[MessageRecord]:
        """Like ``load_messages``, with each message's id and timestamp."""
        ...

    def clear_messages(self, chat_id: str) -> None:
        """Delete a chat's messages; the chat itself is kept."""
        ...

    def count_chats_for_course(self, course_id: str) -> int:
        """Number of chats in a course."""
        ...


@dataclass(slots=True)
class LearningMemory:
    """A durable, course-scoped learning fact, independent of chat history.

    ``course_id`` is None for a global memory. ``source_chat_id`` is provenance
    only: it becomes None if that chat is deleted, and the memory is unaffected.
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

    The foreign keys on ``course_id`` and ``source_chat_id`` must be
    ``ON DELETE SET NULL``: deleting a course or chat never deletes a memory.
    Retire memories with ``archive``; ``delete`` is a separate hard delete.
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
        """Insert a memory and return it with its assigned timestamps."""
        ...

    def get(self, memory_id: str) -> LearningMemory | None:
        """Return a memory by exact id, or None."""
        ...

    def list(
        self,
        *,
        course_id: str | None = UNSET,  # type: ignore[assignment]
        kind: MemoryKind | None = None,
        status: MemoryStatus | None = None,
    ) -> list[LearningMemory]:
        """Memories matching the filters, most recently updated first.

        ``course_id=UNSET`` means any course, ``None`` means global only, and an id
        selects that course. ``kind`` and ``status`` of None mean any.
        """
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
        """Partially update a memory; only the fields provided change.

        ``course_id=UNSET`` leaves it unchanged and ``None`` makes the memory global.
        ``topic``, ``kind`` and ``summary`` of None are left unchanged.
        """
        ...

    def archive(self, memory_id: str) -> LearningMemory:
        """Mark a memory archived and bump ``updated_at``."""
        ...

    def restore(self, memory_id: str) -> LearningMemory:
        """Mark a memory active again and bump ``updated_at``."""
        ...

    def delete(self, memory_id: str) -> None:
        """Permanently delete a memory. Prefer ``archive`` for normal retirement."""
        ...


class CourseRepository(Protocol):
    """Durable storage for course metadata."""

    def create_course(
        self, course_id: str, name: str, code: str | None, term: str | None, description: str | None
    ) -> Course:
        """Insert a course and return it with its assigned timestamps."""
        ...

    def get_course(self, course_id: str) -> Course | None:
        """Return a course by exact id, or None."""
        ...

    def list_courses(self) -> list[Course]:
        """All courses, most recently edited first.

        Chat activity does not change a course's ``updated_at``.
        """
        ...

    def update_course(
        self, course_id: str, name: str, code: str | None, term: str | None, description: str | None
    ) -> Course:
        """Replace a course's editable fields and bump ``updated_at``."""
        ...

    def delete_course(self, course_id: str) -> None:
        """Delete a course. Its chats are kept (``ON DELETE SET NULL`` on
        ``chats.course_id``).
        """
        ...

    def delete_course_archiving_memories(self, course_id: str) -> None:
        """Delete a course and archive its active learning memories in one transaction.

        This is what ``CourseService.delete_course`` calls. It lives on this
        repository because a transaction is scoped to a connection, not a repository;
        ``ON DELETE SET NULL`` alone would turn the course's memories into global
        ones. If either statement fails, both are rolled back. Memories that are
        already global or belong to another course are untouched.
        """
        ...


@dataclass(slots=True)
class LibrarySource:
    """A logical source of study material.

    ``locator`` is metadata only; recording it grants no access to the location.
    ``course_id`` is None for general material. Deleting the course clears it.
    """

    id: str
    course_id: str | None
    kind: LibrarySourceKind
    display_name: str
    locator: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class LibraryFile:
    """One file inside a source, identified by ``(source_id, relative_path)``.

    Holds metadata and processing state only, never file contents. ``indexed_at``
    is when the file last became ``ready``.
    """

    id: str
    source_id: str
    relative_path: str
    display_name: str
    extension: str | None
    size_bytes: int | None
    modified_at: str | None
    content_hash: str | None
    processing_state: LibraryFileState
    failure_code: str | None
    indexed_at: str | None
    created_at: str
    updated_at: str


class LibraryRepository(Protocol):
    """Durable storage for library sources and files.

    ``library_sources.course_id`` is ``ON DELETE SET NULL`` and
    ``library_files.source_id`` is ``ON DELETE CASCADE``. Deleting records
    never touches the filesystem.
    """

    def create_source(
        self, source_id: str, course_id: str | None, kind: LibrarySourceKind, display_name: str, locator: str
    ) -> LibrarySource: ...

    def get_source(self, source_id: str) -> LibrarySource | None: ...

    def find_source(self, kind: LibrarySourceKind, locator: str) -> LibrarySource | None: ...

    def list_sources(self, *, course_id: str | None = UNSET) -> list[LibrarySource]:  # type: ignore[assignment]
        """Sources, most recently updated first. ``course_id=UNSET`` means any course,
        ``None`` means general (no course)."""
        ...

    def update_source(
        self, source_id: str, *, course_id: str | None = UNSET, display_name: str | None = None  # type: ignore[assignment]
    ) -> LibrarySource: ...

    def delete_source(self, source_id: str) -> None:
        """Delete the source and, by cascade, its file records."""
        ...

    def create_file(
        self,
        file_id: str,
        source_id: str,
        relative_path: str,
        display_name: str,
        extension: str | None,
        size_bytes: int | None,
        modified_at: str | None,
        content_hash: str | None,
    ) -> LibraryFile:
        """Insert a ``pending`` file."""
        ...

    def get_file(self, file_id: str) -> LibraryFile | None: ...

    def find_file(self, source_id: str, relative_path: str) -> LibraryFile | None: ...

    def list_files(
        self, *, source_id: str | None = None, state: LibraryFileState | None = None
    ) -> list[LibraryFile]:
        """Files ordered by source and path; filters of None mean any."""
        ...

    def save_file(self, file: LibraryFile) -> LibraryFile:
        """Write the mutable fields of ``file`` and bump ``updated_at``."""
        ...

    def delete_file(self, file_id: str) -> None: ...
