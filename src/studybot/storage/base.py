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

from studybot.core.messages import Message, Role


@dataclass(slots=True)
class ChatSession:
    """Metadata for one persisted (or about-to-be-persisted) chat.

    `title` is `None` for a chat that hasn't received its first user message
    yet — the CLI displays this as "Untitled" and `SessionService` fills it
    in automatically once there's something to derive a title from.

    `course_id` is `None` for a "General" chat not associated with any
    course. Course membership is purely organizational: it never merges or
    shares conversation history between chats.
    """

    id: str
    title: str | None
    course_id: str | None
    created_at: str
    updated_at: str


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

    def create_chat(self, chat_id: str, title: str | None, course_id: str | None = None) -> ChatSession:
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

    def clear_messages(self, chat_id: str) -> None:
        """Delete all messages for a chat, leaving the chat itself intact."""
        ...

    def count_chats_for_course(self, course_id: str) -> int:
        """How many chats currently belong to a course."""
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
