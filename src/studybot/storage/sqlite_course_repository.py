"""SQLite-backed `CourseRepository`.

This is one of three modules allowed to contain SQL (the others are
`sqlite_repository.py` for chats and `sqlite_learning_memory_repository.py`
for learning memory). Everything else — CLI, `CourseService`,
`SessionService`, a future GUI — talks to the `CourseRepository` protocol.

Schema creation and migration are handled by `storage.database`, which owns
the shared `sqlite3.Connection` this repository is given.

`delete_course_archiving_memories` is the one place this module reaches
into the `learning_memories` table directly, rather than only `courses` —
see its docstring in `storage.base.CourseRepository` for why that's a
deliberate, narrow exception (SQLite transactions are connection-scoped,
not repository-scoped) rather than a precedent for repositories reaching
into each other's tables generally.
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
    """Talks to a shared SQLite connection via the standard-library `sqlite3`."""

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
        # Foreign key ON DELETE SET NULL (declared on chats.course_id) clears
        # the association on any chats that belonged to this course; the
        # chats and their messages are never touched by this statement.
        with self._conn:
            self._conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))

    def delete_course_archiving_memories(self, course_id: str) -> None:
        """Archive the course's active memories and delete the course, as
        one atomic SQLite transaction — see the protocol docstring for the
        full rationale. If the `DELETE` fails for any reason, the `UPDATE`
        is rolled back too: `with self._conn:` commits only if the whole
        block completes without raising, and rolls back everything in the
        block otherwise (verified by test, including with a genuinely
        independent second connection to the same database file).
        """
        now = _now()
        with self._conn:
            self._conn.execute(
                "UPDATE learning_memories SET status = ?, updated_at = ? WHERE course_id = ? AND status = ?",
                (MemoryStatus.ARCHIVED.value, now, course_id, MemoryStatus.ACTIVE.value),
            )
            self._conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
