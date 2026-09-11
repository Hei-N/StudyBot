"""Opens the shared SQLite connection and applies schema migrations.

`SQLiteChatRepository` and `SQLiteCourseRepository` both operate on the one
`sqlite3.Connection` returned by `open_database`, so they share one
consistent schema and `chats.course_id` can reference `courses.id` without
needing two separate migration stories.

Versioning uses SQLite's own `PRAGMA user_version` — a small integer stored
in the database header — rather than a bespoke metadata table. There is
deliberately no generic migration framework: each version bump gets one
small, explicit function here, applied in sequence.

Migration atomicity note: Python's `sqlite3` module does NOT include DDL
statements (CREATE/ALTER TABLE, ...) in its implicit transaction handling
when using the `with connection:` context manager — verified empirically,
not folklore. Getting a real all-or-nothing migration therefore requires an
explicit `BEGIN` and `commit()`/`rollback()`, which is what every migration
function here does.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

# Individual statements rather than one `executescript()` call: `sqlite3`'s
# `executescript()` forces an implicit COMMIT before it runs and does not
# participate in an explicit transaction (verified empirically), which would
# silently defeat the atomicity this module exists to guarantee.
_FRESH_SCHEMA_V2_STATEMENTS = [
    """
    CREATE TABLE courses (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        code TEXT,
        term TEXT,
        description TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE chats (
        id TEXT PRIMARY KEY,
        title TEXT,
        course_id TEXT REFERENCES courses(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX idx_messages_chat_id ON messages(chat_id, id)",
    "CREATE INDEX idx_chats_course_id ON chats(course_id)",
]


def open_database(db_path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the chat database at `db_path`, applying
    any pending schema migrations. Safe to call repeatedly and
    idempotent — an already-current database is left untouched."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.debug("Opening chat database at %s", db_path)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        _migrate(connection)
    except BaseException:
        connection.close()
        raise
    return connection


def get_schema_version(connection: sqlite3.Connection) -> int:
    return connection.execute("PRAGMA user_version").fetchone()[0]


def _migrate(connection: sqlite3.Connection) -> None:
    version = get_schema_version(connection)

    if version == 0:
        _create_fresh_v2(connection)
        return

    if version == 1:
        _migrate_v1_to_v2(connection)


def _create_fresh_v2(connection: sqlite3.Connection) -> None:
    """A brand-new database: create the current schema directly, with no
    migration history to replay."""
    try:
        connection.execute("BEGIN")
        for statement in _FRESH_SCHEMA_V2_STATEMENTS:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    """Add course support to a Version 0.1 (schema v1) database.

    All existing chats and messages (ids, titles, timestamps, content) are
    left completely untouched; every chat simply gains `course_id = NULL`
    (an unassigned/"General" chat) via the new column's default. Applied as
    one explicit transaction — if any statement fails, `rollback()` leaves
    the database exactly as it was at schema v1, not partially upgraded.
    """
    logger.debug("Migrating chat database schema from v1 to v2")
    try:
        connection.execute("BEGIN")
        connection.execute(
            """
            CREATE TABLE courses (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                code TEXT,
                term TEXT,
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "ALTER TABLE chats ADD COLUMN course_id TEXT REFERENCES courses(id) ON DELETE SET NULL"
        )
        connection.execute("CREATE INDEX idx_chats_course_id ON chats(course_id)")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
