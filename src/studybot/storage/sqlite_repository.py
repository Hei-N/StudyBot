"""SQLite-backed `ChatRepository`.

This is the only module allowed to contain SQL. Everything else — CLI,
`SessionService`, a future GUI — talks to the `ChatRepository` protocol.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from studybot.core.messages import Message, Role
from studybot.storage.base import ChatSession

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id, id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_session(row: sqlite3.Row) -> ChatSession:
    return ChatSession(
        id=row["id"], title=row["title"], created_at=row["created_at"], updated_at=row["updated_at"]
    )


class SQLiteChatRepository:
    """Talks to a local SQLite database file via the standard-library `sqlite3`.

    Schema is created (and its version recorded via `PRAGMA user_version`,
    SQLite's own lightweight versioning mechanism) on first connection and
    is idempotent — opening the same database repeatedly never recreates or
    corrupts existing tables.
    """

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug("Opening chat database at %s", db_path)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self._conn:
            self._conn.executescript(_SCHEMA)
            current_version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if current_version == 0:
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @property
    def schema_version(self) -> int:
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    def close(self) -> None:
        self._conn.close()

    # --- chats -------------------------------------------------------------

    def create_chat(self, chat_id: str, title: str | None) -> ChatSession:
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO chats (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (chat_id, title, now, now),
            )
        return ChatSession(id=chat_id, title=title, created_at=now, updated_at=now)

    def get_chat(self, chat_id: str) -> ChatSession | None:
        row = self._conn.execute(
            "SELECT id, title, created_at, updated_at FROM chats WHERE id = ?", (chat_id,)
        ).fetchone()
        return _row_to_session(row) if row is not None else None

    def list_chats(self) -> list[ChatSession]:
        rows = self._conn.execute(
            "SELECT id, title, created_at, updated_at FROM chats "
            "ORDER BY updated_at DESC, created_at DESC"
        ).fetchall()
        return [_row_to_session(row) for row in rows]

    def rename_chat(self, chat_id: str, title: str) -> ChatSession:
        now = _now()
        with self._conn:
            self._conn.execute(
                "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?", (title, now, chat_id)
            )
        return self.get_chat(chat_id)

    def touch_chat(self, chat_id: str) -> ChatSession:
        now = _now()
        with self._conn:
            self._conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))
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
