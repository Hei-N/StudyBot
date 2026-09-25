"""Opens the shared SQLite connection and applies schema migrations.

`SQLiteChatRepository`, `SQLiteCourseRepository`, and
`SQLiteLearningMemoryRepository` all operate on the one
`sqlite3.Connection` returned by `open_database`, so they share one
consistent schema and `chats.course_id`/`learning_memories.course_id`/
`learning_memories.source_chat_id` can reference `courses.id`/`chats.id`
without needing separate migration stories.

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

SCHEMA_VERSION = 5

# Individual statements rather than one `executescript()` call: `sqlite3`'s
# `executescript()` forces an implicit COMMIT before it runs and does not
# participate in an explicit transaction (verified empirically), which would
# silently defeat the atomicity this module exists to guarantee.
_FRESH_SCHEMA_STATEMENTS = [
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
        teaching_mode TEXT NOT NULL DEFAULT 'teach',
        reasoning_mode TEXT NOT NULL DEFAULT 'fast',
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
    """
    CREATE TABLE learning_memories (
        id TEXT PRIMARY KEY,
        course_id TEXT REFERENCES courses(id) ON DELETE SET NULL,
        source_chat_id TEXT REFERENCES chats(id) ON DELETE SET NULL,
        topic TEXT NOT NULL,
        kind TEXT NOT NULL,
        summary TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX idx_learning_memories_course_id ON learning_memories(course_id)",
    "CREATE INDEX idx_learning_memories_status ON learning_memories(status)",
    "CREATE INDEX idx_learning_memories_topic ON learning_memories(topic)",
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
        _create_fresh_schema(connection)
        return

    if version == 1:
        _migrate_v1_to_v2(connection)
        version = 2

    if version == 2:
        _migrate_v2_to_v3(connection)
        version = 3

    if version == 3:
        _migrate_v3_to_v4(connection)
        version = 4

    if version == 4:
        _migrate_v4_to_v5(connection)
        version = 5


def _create_fresh_schema(connection: sqlite3.Connection) -> None:
    """A brand-new database: create the current schema directly, with no
    migration history to replay."""
    try:
        connection.execute("BEGIN")
        for statement in _FRESH_SCHEMA_STATEMENTS:
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
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
    """Add per-chat teaching modes to a schema-v2 (Stage 4) database.

    All existing courses, chats, messages, and chat/course associations are
    left completely untouched; every existing chat simply gains
    `teaching_mode = 'teach'` (the deliberate default — see
    `core.teaching_mode.DEFAULT_TEACHING_MODE`) via the new column's
    default. Applied as one explicit transaction — if any statement fails,
    `rollback()` leaves the database exactly as it was at schema v2, not
    partially upgraded.
    """
    logger.debug("Migrating chat database schema from v2 to v3")
    try:
        connection.execute("BEGIN")
        connection.execute(
            "ALTER TABLE chats ADD COLUMN teaching_mode TEXT NOT NULL DEFAULT 'teach'"
        )
        connection.execute("PRAGMA user_version = 3")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
    """Add per-chat reasoning modes to a schema-v3 (Stage 5.7) database.

    All existing courses, chats, messages, chat/course associations, and
    teaching modes are left completely untouched; every existing chat
    simply gains `reasoning_mode = 'fast'` (the deliberate default — see
    `core.reasoning_mode.DEFAULT_REASONING_MODE`) via the new column's
    default. Applied as one explicit transaction — if any statement fails,
    `rollback()` leaves the database exactly as it was at schema v3, not
    partially upgraded.
    """
    logger.debug("Migrating chat database schema from v3 to v4")
    try:
        connection.execute("BEGIN")
        connection.execute(
            "ALTER TABLE chats ADD COLUMN reasoning_mode TEXT NOT NULL DEFAULT 'fast'"
        )
        connection.execute("PRAGMA user_version = 4")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _migrate_v4_to_v5(connection: sqlite3.Connection) -> None:
    """Add the `learning_memories` table to a schema-v4 (Stage 5.8)
    database (Stage 6: Learning Memory Foundation).

    A brand-new table, so nothing about any existing courses, chats,
    messages, teaching modes, or reasoning modes is touched — there is no
    existing learning-memory data to migrate, since the feature didn't
    exist before this version. Applied as one explicit transaction — if
    any statement fails, `rollback()` leaves the database exactly as it
    was at schema v4, not partially upgraded.
    """
    logger.debug("Migrating chat database schema from v4 to v5")
    try:
        connection.execute("BEGIN")
        connection.execute(
            """
            CREATE TABLE learning_memories (
                id TEXT PRIMARY KEY,
                course_id TEXT REFERENCES courses(id) ON DELETE SET NULL,
                source_chat_id TEXT REFERENCES chats(id) ON DELETE SET NULL,
                topic TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute("CREATE INDEX idx_learning_memories_course_id ON learning_memories(course_id)")
        connection.execute("CREATE INDEX idx_learning_memories_status ON learning_memories(status)")
        connection.execute("CREATE INDEX idx_learning_memories_topic ON learning_memories(topic)")
        connection.execute("PRAGMA user_version = 5")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
