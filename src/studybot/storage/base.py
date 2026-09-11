"""Chat persistence abstraction.

Mirrors the `ModelProvider` pattern in `studybot.models`: everything outside
this package and its concrete implementations talks only to `ChatRepository`
and `ChatSession`, never to raw SQL or database rows. A future backend
(e.g. an encrypted store, or a sync-capable one) can replace
`SQLiteChatRepository` without touching `SessionService`, the CLI, or a
future GUI.
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
    """

    id: str
    title: str | None
    created_at: str
    updated_at: str


class ChatRepository(Protocol):
    """Durable storage for chats and their messages.

    Implementations must enforce foreign keys (so deleting a chat deletes
    its messages), use parameterized SQL only, and preserve message
    insertion order exactly.
    """

    def create_chat(self, chat_id: str, title: str | None) -> ChatSession:
        """Insert a new chat row and return it (with server-assigned timestamps)."""
        ...

    def get_chat(self, chat_id: str) -> ChatSession | None:
        """Fetch one chat by its exact id, or None if it doesn't exist."""
        ...

    def list_chats(self) -> list[ChatSession]:
        """All chats, most recently updated first."""
        ...

    def rename_chat(self, chat_id: str, title: str) -> ChatSession:
        """Set a chat's title and bump its `updated_at`."""
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

        Never includes a system message — the system prompt is application
        configuration, injected by `ChatService`, and is never persisted.
        """
        ...

    def clear_messages(self, chat_id: str) -> None:
        """Delete all messages for a chat, leaving the chat itself intact."""
        ...

    def close(self) -> None:
        """Release the underlying database connection."""
        ...
