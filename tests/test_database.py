import sqlite3

import pytest

from studybot.storage.database import SCHEMA_VERSION, get_schema_version, open_database


def test_schema_version_constant_is_9():
    assert SCHEMA_VERSION == 9


def test_fresh_database_starts_directly_at_current_version(tmp_path):
    connection = open_database(tmp_path / "studybot.db")
    try:
        assert get_schema_version(connection) == 9
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"chats", "messages", "courses", "learning_memories"} <= tables
        columns = [row[1] for row in connection.execute("PRAGMA table_info(chats)").fetchall()]
        assert "teaching_mode" in columns
        assert "reasoning_mode" in columns
        memory_columns = [row[1] for row in connection.execute("PRAGMA table_info(learning_memories)").fetchall()]
        assert {"course_id", "source_chat_id", "topic", "kind", "summary", "status"} <= set(memory_columns)
    finally:
        connection.close()


def test_fresh_database_chats_default_to_teach_mode(tmp_path):
    connection = open_database(tmp_path / "studybot.db")
    try:
        connection.execute(
            "INSERT INTO chats (id, title, created_at, updated_at) VALUES ('c1', 'T', 't', 't')"
        )
        connection.commit()
        row = connection.execute("SELECT teaching_mode FROM chats WHERE id = 'c1'").fetchone()
        assert row[0] == "teach"
    finally:
        connection.close()


def test_fresh_database_chats_default_to_fast_reasoning_mode(tmp_path):
    connection = open_database(tmp_path / "studybot.db")
    try:
        connection.execute(
            "INSERT INTO chats (id, title, created_at, updated_at) VALUES ('c1', 'T', 't', 't')"
        )
        connection.commit()
        row = connection.execute("SELECT reasoning_mode FROM chats WHERE id = 'c1'").fetchone()
        assert row[0] == "fast"
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
        "INSERT INTO chats (id, title, course_id, teaching_mode, created_at, updated_at) "
        "VALUES ('chat-1', 'Title', NULL, 'homework', 't', 't')"
    )
    conn1.commit()
    conn1.close()

    conn2 = open_database(db_path)
    try:
        assert get_schema_version(conn2) == 9
        row = conn2.execute(
            "SELECT title, teaching_mode FROM chats WHERE id = 'chat-1'"
        ).fetchone()
        assert row is not None
        assert row[0] == "Title"
        assert row[1] == "homework"
    finally:
        conn2.close()


# --- v1 -> current migration (chained through v2 .. v5) ----------------------------------


def _create_v1_database(db_path):
    """Build a schema-v1 database by hand (``open_database`` always creates the
    current schema) to simulate an old user database.
    """
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


def test_migration_upgrades_v1_database_directly_to_current(tmp_path):
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
        assert get_schema_version(connection) == 9

        chat = connection.execute("SELECT * FROM chats WHERE id = 'chat-1'").fetchone()
        assert chat["title"] == "Old Chat"
        assert chat["created_at"] == "2024-01-01T00:00:00+00:00"
        assert chat["updated_at"] == "2024-01-02T00:00:00+00:00"
        assert chat["course_id"] is None  # existing chats become unassigned
        assert chat["teaching_mode"] == "teach"  # existing chats default to Teach
        assert chat["reasoning_mode"] == "fast"  # existing chats default to Fast

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


def test_v1_migration_is_idempotent_when_run_twice(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v1_database(db_path)
    seed.execute("INSERT INTO chats (id, title, created_at, updated_at) VALUES ('c1', 'T', 't', 't')")
    seed.commit()
    seed.close()

    conn1 = open_database(db_path)
    conn1.close()

    # Reopening an already-migrated (current) database must not re-run any
    # migration (which would fail trying to add a duplicate column/table).
    conn2 = open_database(db_path)
    try:
        assert get_schema_version(conn2) == 9
        assert conn2.execute("SELECT title FROM chats WHERE id = 'c1'").fetchone()[0] == "T"
    finally:
        conn2.close()


def test_v1_to_v2_failed_migration_does_not_leave_a_partially_upgraded_database(tmp_path):
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
        assert "teaching_mode" not in chats_columns
        # The original chat data is completely untouched.
        assert verify.execute("SELECT title FROM chats WHERE id = 'c1'").fetchone()[0] == "T"
    finally:
        verify.close()


# --- v2 -> v3 migration ----------------------------------------------------------------


def _create_v2_database(db_path):
    """Build a schema-v2 database by hand, with a course already in use."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE courses (id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT, term TEXT, "
        "description TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE chats (id TEXT PRIMARY KEY, title TEXT, "
        "course_id TEXT REFERENCES courses(id) ON DELETE SET NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL "
        "REFERENCES chats(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    return conn


def test_migration_upgrades_v2_database_to_current(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v2_database(db_path)
    seed.execute(
        "INSERT INTO courses (id, name, code, term, description, created_at, updated_at) "
        "VALUES ('course-1', 'Physics', 'PHY 215', 'Fall 2026', 'Mechanics', 't1', 't1')"
    )
    seed.execute(
        "INSERT INTO chats (id, title, course_id, created_at, updated_at) VALUES "
        "('chat-1', 'Old Chat', 'course-1', 't2', 't3')"
    )
    seed.execute(
        "INSERT INTO messages (chat_id, role, content, created_at) VALUES "
        "('chat-1', 'user', 'hello from v2', 't2')"
    )
    seed.commit()
    seed.close()

    connection = open_database(db_path)
    try:
        assert get_schema_version(connection) == 9

        course = connection.execute("SELECT * FROM courses WHERE id = 'course-1'").fetchone()
        assert course["name"] == "Physics"
        assert course["code"] == "PHY 215"

        chat = connection.execute("SELECT * FROM chats WHERE id = 'chat-1'").fetchone()
        assert chat["title"] == "Old Chat"
        assert chat["course_id"] == "course-1"  # association preserved
        assert chat["created_at"] == "t2"
        assert chat["updated_at"] == "t3"
        assert chat["teaching_mode"] == "teach"  # deliberate default for existing chats
        assert chat["reasoning_mode"] == "fast"  # deliberate default for existing chats

        message = connection.execute("SELECT * FROM messages WHERE chat_id = 'chat-1'").fetchone()
        assert message["content"] == "hello from v2"
    finally:
        connection.close()


def test_v2_migration_is_idempotent_when_run_twice(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v2_database(db_path)
    seed.execute("INSERT INTO chats (id, title, created_at, updated_at) VALUES ('c1', 'T', 't', 't')")
    seed.commit()
    seed.close()

    conn1 = open_database(db_path)
    conn1.close()

    conn2 = open_database(db_path)
    try:
        assert get_schema_version(conn2) == 9
        row = conn2.execute("SELECT title, teaching_mode, reasoning_mode FROM chats WHERE id = 'c1'").fetchone()
        assert row[0] == "T"
        assert row[1] == "teach"
        assert row[2] == "fast"
    finally:
        conn2.close()


def test_v2_to_v3_failed_migration_does_not_leave_a_partially_upgraded_database(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v2_database(db_path)
    seed.execute("INSERT INTO chats (id, title, created_at, updated_at) VALUES ('c1', 'T', 't', 't')")
    # Sabotage the migration: a `teaching_mode` column already exists, so
    # the migration's own `ALTER TABLE ... ADD COLUMN teaching_mode` fails.
    seed.execute("ALTER TABLE chats ADD COLUMN teaching_mode TEXT")
    seed.execute("PRAGMA user_version = 2")
    seed.commit()
    seed.close()

    with pytest.raises(sqlite3.OperationalError):
        open_database(db_path)

    verify = sqlite3.connect(db_path)
    try:
        assert verify.execute("PRAGMA user_version").fetchone()[0] == 2
        # The original chat data (and the pre-existing column) is untouched.
        assert verify.execute("SELECT title FROM chats WHERE id = 'c1'").fetchone()[0] == "T"
    finally:
        verify.close()


# --- v3 -> v4 migration (reasoning modes) -----------------------------------------------


def _create_v3_database(db_path):
    """Build a schema-v3 database by hand, with a course and a non-default teaching mode in use."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE courses (id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT, term TEXT, "
        "description TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE chats (id TEXT PRIMARY KEY, title TEXT, "
        "course_id TEXT REFERENCES courses(id) ON DELETE SET NULL, "
        "teaching_mode TEXT NOT NULL DEFAULT 'teach', "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL "
        "REFERENCES chats(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    return conn


def test_migration_upgrades_v3_database_to_current(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v3_database(db_path)
    seed.execute(
        "INSERT INTO courses (id, name, code, term, description, created_at, updated_at) "
        "VALUES ('course-1', 'Physics', 'PHY 215', 'Fall 2026', 'Mechanics', 't1', 't1')"
    )
    seed.execute(
        "INSERT INTO chats (id, title, course_id, teaching_mode, created_at, updated_at) VALUES "
        "('chat-1', 'Old Chat', 'course-1', 'homework', 't2', 't3')"
    )
    seed.execute(
        "INSERT INTO messages (chat_id, role, content, created_at) VALUES "
        "('chat-1', 'user', 'hello from v3', 't2')"
    )
    seed.commit()
    seed.close()

    connection = open_database(db_path)
    try:
        assert get_schema_version(connection) == 9

        course = connection.execute("SELECT * FROM courses WHERE id = 'course-1'").fetchone()
        assert course["name"] == "Physics"  # courses untouched

        chat = connection.execute("SELECT * FROM chats WHERE id = 'chat-1'").fetchone()
        assert chat["title"] == "Old Chat"
        assert chat["course_id"] == "course-1"  # course relationship preserved
        assert chat["teaching_mode"] == "homework"  # existing teaching mode preserved exactly
        assert chat["reasoning_mode"] == "fast"  # new column's deliberate default

        message = connection.execute("SELECT * FROM messages WHERE chat_id = 'chat-1'").fetchone()
        assert message["content"] == "hello from v3"
    finally:
        connection.close()


def test_v3_migration_is_idempotent_when_run_twice(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v3_database(db_path)
    seed.execute(
        "INSERT INTO chats (id, title, teaching_mode, created_at, updated_at) VALUES "
        "('c1', 'T', 'exam', 't', 't')"
    )
    seed.commit()
    seed.close()

    conn1 = open_database(db_path)
    conn1.close()

    # Reopening an already-migrated (current) database must not re-run any
    # migration (which would fail trying to add a duplicate column).
    conn2 = open_database(db_path)
    try:
        assert get_schema_version(conn2) == 9
        row = conn2.execute("SELECT title, teaching_mode, reasoning_mode FROM chats WHERE id = 'c1'").fetchone()
        assert row[0] == "T"
        assert row[1] == "exam"
        assert row[2] == "fast"
    finally:
        conn2.close()


def test_v3_to_v4_failed_migration_does_not_leave_a_partially_upgraded_database(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v3_database(db_path)
    seed.execute(
        "INSERT INTO chats (id, title, teaching_mode, created_at, updated_at) VALUES "
        "('c1', 'T', 'teach', 't', 't')"
    )
    # Sabotage the migration: a `reasoning_mode` column already exists, so
    # the migration's own `ALTER TABLE ... ADD COLUMN reasoning_mode` fails.
    seed.execute("ALTER TABLE chats ADD COLUMN reasoning_mode TEXT")
    seed.execute("PRAGMA user_version = 3")
    seed.commit()
    seed.close()

    with pytest.raises(sqlite3.OperationalError):
        open_database(db_path)

    verify = sqlite3.connect(db_path)
    try:
        assert verify.execute("PRAGMA user_version").fetchone()[0] == 3
        # The original chat data (and the pre-existing column) is untouched.
        assert verify.execute("SELECT title FROM chats WHERE id = 'c1'").fetchone()[0] == "T"
    finally:
        verify.close()


# --- v4 -> v5 migration (learning memory) -----------------------------------------------


def _create_v4_database(db_path):
    """Build a schema-v4 database by hand, with a course, a chat and a message and
    no ``learning_memories`` table.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE courses (id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT, term TEXT, "
        "description TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE chats (id TEXT PRIMARY KEY, title TEXT, "
        "course_id TEXT REFERENCES courses(id) ON DELETE SET NULL, "
        "teaching_mode TEXT NOT NULL DEFAULT 'teach', "
        "reasoning_mode TEXT NOT NULL DEFAULT 'fast', "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL "
        "REFERENCES chats(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute("PRAGMA user_version = 4")
    conn.commit()
    return conn


def test_migration_upgrades_v4_database_to_current(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v4_database(db_path)
    seed.execute(
        "INSERT INTO courses (id, name, code, term, description, created_at, updated_at) "
        "VALUES ('course-1', 'Physics', 'PHY 215', 'Fall 2026', 'Mechanics', 't1', 't1')"
    )
    seed.execute(
        "INSERT INTO chats (id, title, course_id, teaching_mode, reasoning_mode, created_at, updated_at) VALUES "
        "('chat-1', 'Old Chat', 'course-1', 'homework', 'deep', 't2', 't3')"
    )
    seed.execute(
        "INSERT INTO messages (chat_id, role, content, created_at) VALUES "
        "('chat-1', 'user', 'hello from v4', 't2')"
    )
    seed.commit()
    seed.close()

    connection = open_database(db_path)
    try:
        assert get_schema_version(connection) == 9

        course = connection.execute("SELECT * FROM courses WHERE id = 'course-1'").fetchone()
        assert course["name"] == "Physics"  # courses untouched

        chat = connection.execute("SELECT * FROM chats WHERE id = 'chat-1'").fetchone()
        assert chat["title"] == "Old Chat"
        assert chat["course_id"] == "course-1"
        assert chat["teaching_mode"] == "homework"  # existing modes preserved exactly
        assert chat["reasoning_mode"] == "deep"

        message = connection.execute("SELECT * FROM messages WHERE chat_id = 'chat-1'").fetchone()
        assert message["content"] == "hello from v4"

        # The new table exists, is empty, and has the expected shape.
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "learning_memories" in tables
        count = connection.execute("SELECT COUNT(*) FROM learning_memories").fetchone()[0]
        assert count == 0
    finally:
        connection.close()


def test_v4_migration_is_idempotent_when_run_twice(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v4_database(db_path)
    seed.execute(
        "INSERT INTO chats (id, title, teaching_mode, reasoning_mode, created_at, updated_at) VALUES "
        "('c1', 'T', 'exam', 'deep', 't', 't')"
    )
    seed.commit()
    seed.close()

    conn1 = open_database(db_path)
    conn1.close()

    # Reopening an already-migrated (current) database must not re-run any
    # migration (which would fail trying to create a duplicate table).
    conn2 = open_database(db_path)
    try:
        assert get_schema_version(conn2) == 9
        row = conn2.execute("SELECT title, teaching_mode, reasoning_mode FROM chats WHERE id = 'c1'").fetchone()
        assert row[0] == "T"
        assert row[1] == "exam"
        assert row[2] == "deep"
    finally:
        conn2.close()


def test_v4_to_v5_failed_migration_does_not_leave_a_partially_upgraded_database(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v4_database(db_path)
    seed.execute(
        "INSERT INTO chats (id, title, teaching_mode, reasoning_mode, created_at, updated_at) VALUES "
        "('c1', 'T', 'teach', 'fast', 't', 't')"
    )
    # Sabotage the migration: a conflicting `learning_memories` table
    # already exists, so the migration's own `CREATE TABLE
    # learning_memories` will fail partway through its transaction.
    seed.execute("CREATE TABLE learning_memories (bogus INTEGER)")
    seed.execute("PRAGMA user_version = 4")
    seed.commit()
    seed.close()

    with pytest.raises(sqlite3.OperationalError):
        open_database(db_path)

    verify = sqlite3.connect(db_path)
    try:
        assert verify.execute("PRAGMA user_version").fetchone()[0] == 4
        columns = [row[1] for row in verify.execute("PRAGMA table_info(learning_memories)").fetchall()]
        assert columns == ["bogus"]  # the real schema was never created
        # The original chat data is completely untouched.
        assert verify.execute("SELECT title FROM chats WHERE id = 'c1'").fetchone()[0] == "T"
    finally:
        verify.close()


# --- foreign key behavior: course/chat deletion never destroys a memory ----------------


def test_deleting_source_chat_sets_source_chat_id_null_but_keeps_the_memory(tmp_path):
    from studybot.storage.sqlite_learning_memory_repository import SQLiteLearningMemoryRepository
    from studybot.storage.sqlite_repository import SQLiteChatRepository
    from studybot.core.learning_memory import MemoryKind

    connection = open_database(tmp_path / "studybot.db")
    try:
        chats = SQLiteChatRepository(connection)
        memories = SQLiteLearningMemoryRepository(connection)
        chat = chats.create_chat("chat-1", "Physics chat")
        memory = memories.create(
            "mem-1", None, chat.id, "Vector components", MemoryKind.NEEDS_REVIEW, "Mixes x/y components."
        )

        chats.delete_chat(chat.id)

        survived = memories.get(memory.id)
        assert survived is not None
        assert survived.source_chat_id is None
        assert survived.topic == "Vector components"
    finally:
        connection.close()


def test_deleting_course_sets_course_id_null_but_keeps_the_memory(tmp_path):
    from studybot.storage.sqlite_course_repository import SQLiteCourseRepository
    from studybot.storage.sqlite_learning_memory_repository import SQLiteLearningMemoryRepository
    from studybot.core.learning_memory import MemoryKind

    connection = open_database(tmp_path / "studybot.db")
    try:
        courses = SQLiteCourseRepository(connection)
        memories = SQLiteLearningMemoryRepository(connection)
        course = courses.create_course("course-1", "Physics", None, None, None)
        memory = memories.create(
            "mem-1", course.id, None, "Vector components", MemoryKind.NEEDS_REVIEW, "Mixes x/y components."
        )

        courses.delete_course(course.id)

        survived = memories.get(memory.id)
        assert survived is not None
        assert survived.course_id is None
        assert survived.topic == "Vector components"
    finally:
        connection.close()
