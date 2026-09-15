"""SQLite-backed `ChatRepository`.

This is one of two modules allowed to contain SQL (the other is
`sqlite_course_repository.py`). Everything else — CLI, `SessionService`,
`CourseService`, a future GUI — talks to the `ChatRepository` protocol.

Schema creation and migration are handled by `storage.database`, which owns
the shared `sqlite3.Connection` this repository is given.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from studybot.core.messages import Message, Role
from studybot.core.teaching_mode import DEFAULT_TEACHING_MODE, TeachingMode
from studybot.storage.base import ChatSession

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_stored_mode(value: str) -> TeachingMode:
    """Convert a stored mode string to `TeachingMode` at the repository
    boundary. An unrecognized value (e.g. from manual DB tampering or a
    future downgrade) never propagates as a raw string — it deliberately
    falls back to the default mode, logged for visibility."""
    try:
        return TeachingMode(value)
    except ValueError:
        logger.warning("Unknown teaching_mode %r in database; falling back to default", value)
        return DEFAULT_TEACHING_MODE


def _row_to_session(row: sqlite3.Row) -> ChatSession:
    return ChatSession(
        id=row["id"],
        title=row["title"],
        course_id=row["course_id"],
        teaching_mode=_parse_stored_mode(row["teaching_mode"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SQLiteChatRepository:
    """Talks to a shared SQLite connection via the standard-library `sqlite3`."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    # --- chats -------------------------------------------------------------

    def create_chat(
        self,
        chat_id: str,
        title: str | None,
        course_id: str | None = None,
        teaching_mode: TeachingMode = DEFAULT_TEACHING_MODE,
    ) -> ChatSession:
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO chats (id, title, course_id, teaching_mode, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, title, course_id, teaching_mode.value, now, now),
            )
        return ChatSession(
            id=chat_id, title=title, course_id=course_id, teaching_mode=teaching_mode,
            created_at=now, updated_at=now,
        )

    def get_chat(self, chat_id: str) -> ChatSession | None:
        row = self._conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        return _row_to_session(row) if row is not None else None

    def list_chats(self) -> list[ChatSession]:
        rows = self._conn.execute(
            "SELECT * FROM chats ORDER BY updated_at DESC, created_at DESC"
        ).fetchall()
        return [_row_to_session(row) for row in rows]

    def list_chats_by_course(self, course_id: str | None) -> list[ChatSession]:
        if course_id is None:
            rows = self._conn.execute(
                "SELECT * FROM chats WHERE course_id IS NULL ORDER BY updated_at DESC, created_at DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM chats WHERE course_id = ? ORDER BY updated_at DESC, created_at DESC",
                (course_id,),
            ).fetchall()
        return [_row_to_session(row) for row in rows]

    def rename_chat(self, chat_id: str, title: str) -> ChatSession:
        now = _now()
        with self._conn:
            self._conn.execute(
                "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?", (title, now, chat_id)
            )
        return self.get_chat(chat_id)

    def move_chat_to_course(self, chat_id: str, course_id: str | None) -> ChatSession:
        now = _now()
        with self._conn:
            self._conn.execute(
                "UPDATE chats SET course_id = ?, updated_at = ? WHERE id = ?", (course_id, now, chat_id)
            )
        return self.get_chat(chat_id)

    def touch_chat(self, chat_id: str) -> ChatSession:
        now = _now()
        with self._conn:
            self._conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))
        return self.get_chat(chat_id)

    def set_teaching_mode(self, chat_id: str, mode: TeachingMode) -> ChatSession:
        now = _now()
        with self._conn:
            self._conn.execute(
                "UPDATE chats SET teaching_mode = ?, updated_at = ? WHERE id = ?",
                (mode.value, now, chat_id),
            )
        return self.get_chat(chat_id)

    def delete_chat(self, chat_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))

    # --- messages ------------------------------------------------------------

    def append_message(self, chat_id: str, role: Role, content: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, role.value, content, _now()),
            )

    def load_messages(self, chat_id: str) -> list[Message]:
        rows = self._conn.execute(
            "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id ASC", (chat_id,)
        ).fetchall()
        return [Message(role=Role(row["role"]), content=row["content"]) for row in rows]

    def clear_messages(self, chat_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))

    def count_chats_for_course(self, course_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM chats WHERE course_id = ?", (course_id,)
        ).fetchone()
        return row[0]
