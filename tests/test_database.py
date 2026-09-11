import sqlite3

import pytest

from studybot.storage.database import SCHEMA_VERSION, get_schema_version, open_database


def test_schema_version_constant_is_2():
    assert SCHEMA_VERSION == 2


def test_fresh_database_starts_directly_at_v2(tmp_path):
    connection = open_database(tmp_path / "studybot.db")
    try:
        assert get_schema_version(connection) == 2
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"chats", "messages", "courses"} <= tables
    finally:
        connection.close()


def test_database_file_is_created_inside_given_directory(tmp_path):
    db_path = tmp_path / "nested" / "studybot.db"
    connection = open_database(db_path)
    try:
        assert db_path.is_file()
    finally:
        connection.close()


def test_foreign_keys_enabled_on_fresh_database(tmp_path):
    connection = open_database(tmp_path / "studybot.db")
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        connection.close()


def test_opening_the_same_database_twice_is_idempotent(tmp_path):
    db_path = tmp_path / "studybot.db"

    conn1 = open_database(db_path)
    conn1.execute(
        "INSERT INTO chats (id, title, course_id, created_at, updated_at) "
        "VALUES ('chat-1', 'Title', NULL, 't', 't')"
    )
    conn1.commit()
    conn1.close()

    conn2 = open_database(db_path)
    try:
        assert get_schema_version(conn2) == 2
        row = conn2.execute("SELECT title FROM chats WHERE id = 'chat-1'").fetchone()
        assert row is not None
        assert row[0] == "Title"
    finally:
        conn2.close()


# --- v1 -> v2 migration --------------------------------------------------------------


def _create_v1_database(db_path):
    """Build a schema-v1 (Stage 3) database by hand, bypassing `open_database`
    (which always creates the *current* schema), to simulate a real
    Version 0.1 user database."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE chats (id TEXT PRIMARY KEY, title TEXT, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL "
        "REFERENCES chats(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    return conn


def test_migration_upgrades_v1_database_to_v2(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v1_database(db_path)
    seed.execute(
        "INSERT INTO chats (id, title, created_at, updated_at) VALUES "
        "('chat-1', 'Old Chat', '2024-01-01T00:00:00+00:00', '2024-01-02T00:00:00+00:00')"
    )
    seed.execute(
        "INSERT INTO messages (chat_id, role, content, created_at) VALUES "
        "('chat-1', 'user', 'hello from v1', '2024-01-01T00:00:01+00:00')"
    )
    seed.commit()
    seed.close()

    connection = open_database(db_path)
    try:
        assert get_schema_version(connection) == 2

        chat = connection.execute("SELECT * FROM chats WHERE id = 'chat-1'").fetchone()
        assert chat["title"] == "Old Chat"
        assert chat["created_at"] == "2024-01-01T00:00:00+00:00"
        assert chat["updated_at"] == "2024-01-02T00:00:00+00:00"
        assert chat["course_id"] is None  # existing chats become unassigned

        message = connection.execute("SELECT * FROM messages WHERE chat_id = 'chat-1'").fetchone()
        assert message["content"] == "hello from v1"
        assert message["role"] == "user"

        courses = connection.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
        assert courses == 0
    finally:
        connection.close()


def test_migration_preserves_multiple_chats_and_message_order(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v1_database(db_path)
    for chat_id, title in [("c1", "First"), ("c2", "Second")]:
        seed.execute(
            "INSERT INTO chats (id, title, created_at, updated_at) VALUES (?, ?, 't', 't')",
            (chat_id, title),
        )
    for role, content in [("user", "one"), ("assistant", "two"), ("user", "three")]:
        seed.execute(
            "INSERT INTO messages (chat_id, role, content, created_at) VALUES ('c1', ?, ?, 't')",
            (role, content),
        )
    seed.commit()
    seed.close()

    connection = open_database(db_path)
    try:
        chat_ids = {row[0] for row in connection.execute("SELECT id FROM chats").fetchall()}
        assert chat_ids == {"c1", "c2"}

        messages = connection.execute(
            "SELECT content FROM messages WHERE chat_id = 'c1' ORDER BY id ASC"
        ).fetchall()
        assert [m[0] for m in messages] == ["one", "two", "three"]
    finally:
        connection.close()


def test_migration_is_idempotent_when_run_twice(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v1_database(db_path)
    seed.execute("INSERT INTO chats (id, title, created_at, updated_at) VALUES ('c1', 'T', 't', 't')")
    seed.commit()
    seed.close()

    conn1 = open_database(db_path)
    conn1.close()

    # Reopening an already-migrated (v2) database must not re-run the v1->v2
    # migration (which would fail trying to add a duplicate column/table).
    conn2 = open_database(db_path)
    try:
        assert get_schema_version(conn2) == 2
        assert conn2.execute("SELECT title FROM chats WHERE id = 'c1'").fetchone()[0] == "T"
    finally:
        conn2.close()


def test_failed_migration_does_not_leave_a_partially_upgraded_database(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v1_database(db_path)
    seed.execute("INSERT INTO chats (id, title, created_at, updated_at) VALUES ('c1', 'T', 't', 't')")
    # Sabotage the migration: a conflicting `courses` table already exists,
    # so the migration's own `CREATE TABLE courses` will fail partway
    # through its transaction.
    seed.execute("CREATE TABLE courses (bogus INTEGER)")
    seed.execute("PRAGMA user_version = 1")
    seed.commit()
    seed.close()

    with pytest.raises(sqlite3.OperationalError):
        open_database(db_path)

    # Verify on a fresh connection that nothing was left half-upgraded.
    verify = sqlite3.connect(db_path)
    try:
        assert verify.execute("PRAGMA user_version").fetchone()[0] == 1
        chats_columns = [row[1] for row in verify.execute("PRAGMA table_info(chats)").fetchall()]
        assert "course_id" not in chats_columns
        # The original chat data is completely untouched.
        assert verify.execute("SELECT title FROM chats WHERE id = 'c1'").fetchone()[0] == "T"
    finally:
        verify.close()
