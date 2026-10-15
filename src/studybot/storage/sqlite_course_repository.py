"""SQLite-backed ``CourseRepository``.

One of three modules that contain SQL; see ``sqlite_repository.py``.
``delete_course_archiving_memories`` also touches ``learning_memories``, a
deliberate exception because a transaction is scoped to the connection (see
``CourseRepository``).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from studybot.core.learning_memory import MemoryStatus
from studybot.storage.base import Course


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_course(row: sqlite3.Row) -> Course:
    return Course(
        id=row["id"],
        name=row["name"],
        code=row["code"],
        term=row["term"],
        description=row["description"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SQLiteCourseRepository:
    """``CourseRepository`` over a shared SQLite connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def create_course(
        self, course_id: str, name: str, code: str | None, term: str | None, description: str | None
    ) -> Course:
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO courses (id, name, code, term, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (course_id, name, code, term, description, now, now),
            )
        return Course(
            id=course_id, name=name, code=code, term=term, description=description,
            created_at=now, updated_at=now,
        )

    def get_course(self, course_id: str) -> Course | None:
        row = self._conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        return _row_to_course(row) if row is not None else None

    def list_courses(self) -> list[Course]:
        rows = self._conn.execute(
            "SELECT * FROM courses ORDER BY updated_at DESC, created_at DESC"
        ).fetchall()
        return [_row_to_course(row) for row in rows]

    def update_course(
        self, course_id: str, name: str, code: str | None, term: str | None, description: str | None
    ) -> Course:
        now = _now()
        with self._conn:
            self._conn.execute(
                "UPDATE courses SET name = ?, code = ?, term = ?, description = ?, updated_at = ? "
                "WHERE id = ?",
                (name, code, term, description, now, course_id),
            )
        return self.get_course(course_id)

    def delete_course(self, course_id: str) -> None:
        # ON DELETE SET NULL on chats.course_id clears the association; chats and
        # messages are untouched.
        with self._conn:
            self._conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))

    def delete_course_archiving_memories(self, course_id: str) -> None:
        """Archive the course's active memories and delete the course in one transaction.

        If the ``DELETE`` fails, the ``UPDATE`` rolls back too: ``with self._conn:``
        commits only if the whole block succeeds.
        """
        now = _now()
        with self._conn:
            self._conn.execute(
                "UPDATE learning_memories SET status = ?, updated_at = ? WHERE course_id = ? AND status = ?",
                (MemoryStatus.ARCHIVED.value, now, course_id, MemoryStatus.ACTIVE.value),
            )
            self._conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
