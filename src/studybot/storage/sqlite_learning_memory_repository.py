"""SQLite-backed ``LearningMemoryRepository``.

One of three modules that contain SQL; see ``sqlite_repository.py``.
``ON DELETE SET NULL`` on both foreign keys (declared in ``storage.database``)
clears ``course_id``/``source_chat_id`` when a course or chat is deleted; this
repository issues no cleanup SQL for that.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from studybot.core.learning_memory import DEFAULT_MEMORY_STATUS, MemoryKind, MemoryStatus
from studybot.storage.base import UNSET, LearningMemory

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_stored_kind(value: str) -> MemoryKind:
    """Convert a stored kind string to ``MemoryKind``.

    An unrecognized value (manual edits, a downgrade) is logged and falls back to
    ``LEARNING_GOAL``, which never takes part in conflict resolution.
    """
    try:
        return MemoryKind(value)
    except ValueError:
        logger.warning("Unknown learning memory kind %r in database; falling back to learning_goal", value)
        return MemoryKind.LEARNING_GOAL


def _parse_stored_status(value: str) -> MemoryStatus:
    try:
        return MemoryStatus(value)
    except ValueError:
        logger.warning("Unknown learning memory status %r in database; falling back to active", value)
        return MemoryStatus.ACTIVE


def _row_to_memory(row: sqlite3.Row) -> LearningMemory:
    return LearningMemory(
        id=row["id"],
        course_id=row["course_id"],
        source_chat_id=row["source_chat_id"],
        topic=row["topic"],
        kind=_parse_stored_kind(row["kind"]),
        summary=row["summary"],
        status=_parse_stored_status(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SQLiteLearningMemoryRepository:
    """``LearningMemoryRepository`` over a shared SQLite connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

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
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO learning_memories "
                "(id, course_id, source_chat_id, topic, kind, summary, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (memory_id, course_id, source_chat_id, topic, kind.value, summary, status.value, now, now),
            )
        return LearningMemory(
            id=memory_id,
            course_id=course_id,
            source_chat_id=source_chat_id,
            topic=topic,
            kind=kind,
            summary=summary,
            status=status,
            created_at=now,
            updated_at=now,
        )

    def get(self, memory_id: str) -> LearningMemory | None:
        row = self._conn.execute("SELECT * FROM learning_memories WHERE id = ?", (memory_id,)).fetchone()
        return _row_to_memory(row) if row is not None else None

    def list(
        self,
        *,
        course_id: str | None = UNSET,  # type: ignore[assignment]
        kind: MemoryKind | None = None,
        status: MemoryStatus | None = None,
    ) -> list[LearningMemory]:
        clauses: list[str] = []
        params: list[object] = []

        if course_id is not UNSET:
            if course_id is None:
                clauses.append("course_id IS NULL")
            else:
                clauses.append("course_id = ?")
                params.append(course_id)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind.value)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM learning_memories{where} ORDER BY updated_at DESC, created_at DESC",
            params,
        ).fetchall()
        return [_row_to_memory(row) for row in rows]

    def update(
        self,
        memory_id: str,
        *,
        course_id: str | None = UNSET,  # type: ignore[assignment]
        topic: str | None = None,
        kind: MemoryKind | None = None,
        summary: str | None = None,
    ) -> LearningMemory:
        fields: list[str] = []
        params: list[object] = []

        if course_id is not UNSET:
            fields.append("course_id = ?")
            params.append(course_id)
        if topic is not None:
            fields.append("topic = ?")
            params.append(topic)
        if kind is not None:
            fields.append("kind = ?")
            params.append(kind.value)
        if summary is not None:
            fields.append("summary = ?")
            params.append(summary)

        fields.append("updated_at = ?")
        params.append(_now())
        params.append(memory_id)

        with self._conn:
            self._conn.execute(f"UPDATE learning_memories SET {', '.join(fields)} WHERE id = ?", params)
        return self.get(memory_id)

    def archive(self, memory_id: str) -> LearningMemory:
        now = _now()
        with self._conn:
            self._conn.execute(
                "UPDATE learning_memories SET status = ?, updated_at = ? WHERE id = ?",
                (MemoryStatus.ARCHIVED.value, now, memory_id),
            )
        return self.get(memory_id)

    def restore(self, memory_id: str) -> LearningMemory:
        now = _now()
        with self._conn:
            self._conn.execute(
                "UPDATE learning_memories SET status = ?, updated_at = ? WHERE id = ?",
                (MemoryStatus.ACTIVE.value, now, memory_id),
            )
        return self.get(memory_id)

    def delete(self, memory_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM learning_memories WHERE id = ?", (memory_id,))
