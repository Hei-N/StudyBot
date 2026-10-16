"""Opens the shared SQLite connection and applies schema migrations.

All repositories use the one ``sqlite3.Connection`` returned by
``open_database``, so they share a schema and foreign keys can span tables.

The schema version is stored in ``PRAGMA user_version``. There is no migration
framework: each version bump is one explicit function, applied in sequence.

Python's ``sqlite3`` does not include DDL in its implicit transactions, so each
migration uses an explicit ``BEGIN`` and ``commit()``/``rollback()`` to be
all-or-nothing.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 8

# Individual statements instead of executescript(), which commits implicitly
# and would defeat the explicit transaction.
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

# Study library tables (added in v6); shared by the fresh schema and the v5 -> v6 migration.
_LIBRARY_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE library_sources (
        id TEXT PRIMARY KEY,
        course_id TEXT REFERENCES courses(id) ON DELETE SET NULL,
        kind TEXT NOT NULL CHECK (kind IN ('local_folder', 'local_file')),
        display_name TEXT NOT NULL,
        locator TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (kind, locator)
    )
    """,
    "CREATE INDEX idx_library_sources_course_id ON library_sources(course_id)",
    """
    CREATE TABLE library_files (
        id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL REFERENCES library_sources(id) ON DELETE CASCADE,
        relative_path TEXT NOT NULL,
        display_name TEXT NOT NULL,
        extension TEXT,
        size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
        modified_at TEXT,
        content_hash TEXT,
        processing_state TEXT NOT NULL DEFAULT 'pending'
            CHECK (processing_state IN ('pending', 'indexing', 'ready', 'failed', 'stale')),
        failure_code TEXT,
        indexed_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (source_id, relative_path),
        CHECK (processing_state != 'ready' OR content_hash IS NOT NULL)
    )
    """,
    "CREATE INDEX idx_library_files_processing_state ON library_files(processing_state)",
]

# Per-source access grants (added in v7); shared by the fresh schema and the v6 -> v7 migration.
_LIBRARY_AUTHORIZATION_STATEMENTS = [
    """
    CREATE TABLE library_source_authorizations (
        source_id TEXT PRIMARY KEY REFERENCES library_sources(id) ON DELETE CASCADE,
        platform TEXT NOT NULL CHECK (platform IN ('macos')),
        authorization_kind TEXT NOT NULL CHECK (authorization_kind IN ('security_scoped_bookmark')),
        authorization_data BLOB NOT NULL CHECK (length(authorization_data) > 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
]

# Page-level extraction storage (added in v8); shared by the fresh schema and the v7 -> v8 migration.
_LIBRARY_PAGE_STATEMENTS = [
    "ALTER TABLE library_files ADD COLUMN page_count INTEGER CHECK (page_count IS NULL OR page_count >= 0)",
    "ALTER TABLE library_files ADD COLUMN text_page_count INTEGER CHECK (text_page_count IS NULL OR text_page_count >= 0)",
    "ALTER TABLE library_files ADD COLUMN processing_version TEXT",
    """
    CREATE TABLE library_pages (
        file_id TEXT NOT NULL REFERENCES library_files(id) ON DELETE CASCADE,
        page_number INTEGER NOT NULL CHECK (page_number >= 1),
        text_content TEXT NOT NULL,
        char_count INTEGER NOT NULL CHECK (char_count >= 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (file_id, page_number)
    )
    """,
]


def open_database(db_path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the database at ``db_path`` and apply pending
    migrations. Idempotent: a current database is left untouched.
    """
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

    if version == 5:
        _migrate_v5_to_v6(connection)
        version = 6

    if version == 6:
        _migrate_v6_to_v7(connection)
        version = 7

    if version == 7:
        _migrate_v7_to_v8(connection)
        version = 8


def _create_fresh_schema(connection: sqlite3.Connection) -> None:
    """Create the current schema directly for a new database."""
    try:
        connection.execute("BEGIN")
        for statement in (
            *_FRESH_SCHEMA_STATEMENTS,
            *_LIBRARY_SCHEMA_STATEMENTS,
            *_LIBRARY_AUTHORIZATION_STATEMENTS,
            *_LIBRARY_PAGE_STATEMENTS,
        ):
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    """Add courses: a ``courses`` table and a nullable ``chats.course_id``.

    Existing chats become General (``course_id = NULL``). One transaction.
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
    """Add ``chats.teaching_mode`` (default 'teach').

    Existing data is untouched. One transaction.
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
    """Add ``chats.reasoning_mode`` (default 'fast').

    Existing data is untouched. One transaction.
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
    """Add the ``learning_memories`` table.

    Existing data is untouched. One transaction.
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


def _migrate_v5_to_v6(connection: sqlite3.Connection) -> None:
    """Add the ``library_sources`` and ``library_files`` tables.

    Existing data is untouched. One transaction.
    """
    logger.debug("Migrating chat database schema from v5 to v6")
    try:
        connection.execute("BEGIN")
        for statement in _LIBRARY_SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 6")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _migrate_v6_to_v7(connection: sqlite3.Connection) -> None:
    """Add the ``library_source_authorizations`` table.

    Existing sources get no authorization record. One transaction.
    """
    logger.debug("Migrating chat database schema from v6 to v7")
    try:
        connection.execute("BEGIN")
        for statement in _LIBRARY_AUTHORIZATION_STATEMENTS:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 7")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _migrate_v7_to_v8(connection: sqlite3.Connection) -> None:
    """Add extraction metadata columns to ``library_files`` and the ``library_pages`` table.

    Existing files keep NULL metadata and have no pages. One transaction.
    """
    logger.debug("Migrating chat database schema from v7 to v8")
    try:
        connection.execute("BEGIN")
        for statement in _LIBRARY_PAGE_STATEMENTS:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 8")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
