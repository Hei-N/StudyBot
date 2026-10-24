import sqlite3

import pytest

from studybot.core.course_service import CourseService
from studybot.core.learning_memory import MemoryKind, MemoryStatus
from studybot.core.library import LibraryFileState, LibrarySourceKind
from studybot.storage.database import SCHEMA_VERSION, get_schema_version, open_database
from studybot.storage.sqlite_course_repository import SQLiteCourseRepository
from studybot.storage.sqlite_learning_memory_repository import SQLiteLearningMemoryRepository
from studybot.storage.sqlite_library_repository import SQLiteLibraryRepository
from studybot.storage.sqlite_repository import SQLiteChatRepository


@pytest.fixture
def connection(tmp_path):
    conn = open_database(tmp_path / "studybot-test.db")
    yield conn
    conn.close()


def _names(connection, kind):
    return {row[0] for row in connection.execute(f"SELECT name FROM sqlite_master WHERE type='{kind}'")}


# --- fresh database ------------------------------------------------------------------


def test_fresh_database_has_the_library_tables_and_keeps_the_old_ones(connection):
    assert get_schema_version(connection) == SCHEMA_VERSION == 9
    assert {"courses", "chats", "messages", "learning_memories", "library_sources", "library_files"} <= _names(
        connection, "table"
    )


def test_fresh_database_library_foreign_keys(connection):
    source_fks = {(r["from"], r["table"], r["on_delete"]) for r in connection.execute("PRAGMA foreign_key_list(library_sources)")}
    file_fks = {(r["from"], r["table"], r["on_delete"]) for r in connection.execute("PRAGMA foreign_key_list(library_files)")}

    assert source_fks == {("course_id", "courses", "SET NULL")}
    assert file_fks == {("source_id", "library_sources", "CASCADE")}


def test_fresh_database_library_indexes_and_uniqueness(connection):
    indexes = _names(connection, "index")
    assert {"idx_library_sources_course_id", "idx_library_files_processing_state"} <= indexes

    unique_columns = []
    for table in ("library_sources", "library_files"):
        for index in connection.execute(f"PRAGMA index_list({table})"):
            if index["unique"] and index["origin"] == "u":
                unique_columns.append([c["name"] for c in connection.execute(f"PRAGMA index_info({index['name']})")])
    assert sorted(unique_columns) == [["kind", "locator"], ["source_id", "relative_path"]]


# --- constraints ---------------------------------------------------------------------


def _insert_source(connection, source_id="s1", course_id=None, kind="local_folder", locator="/x"):
    connection.execute(
        "INSERT INTO library_sources (id, course_id, kind, display_name, locator, created_at, updated_at) "
        "VALUES (?, ?, ?, 'n', ?, 't', 't')",
        (source_id, course_id, kind, locator),
    )


def _insert_file(connection, file_id="f1", source_id="s1", path="a.pdf", state="pending", content_hash=None):
    connection.execute(
        "INSERT INTO library_files (id, source_id, relative_path, display_name, content_hash, processing_state, "
        "created_at, updated_at) VALUES (?, ?, ?, 'n', ?, ?, 't', 't')",
        (file_id, source_id, path, content_hash, state),
    )


def test_invalid_foreign_keys_do_not_silently_succeed(connection):
    with pytest.raises(sqlite3.IntegrityError):
        _insert_source(connection, course_id="no-such-course")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_file(connection, source_id="no-such-source")


def test_check_constraints_reject_bad_values(connection):
    _insert_source(connection)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_source(connection, "s2", kind="google_drive", locator="/y")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_file(connection, state="bogus")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_file(connection, "f2", state="ready", content_hash=None)  # ready needs a hash
    _insert_file(connection, "f3", path="ok.pdf", state="ready", content_hash="a" * 64)


def test_unique_constraints(connection):
    _insert_source(connection)
    _insert_file(connection)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_source(connection, "s2")  # same kind + locator
    with pytest.raises(sqlite3.IntegrityError):
        _insert_file(connection, "f2")  # same source + path
    _insert_source(connection, "s2", locator="/other")
    _insert_file(connection, "f2", source_id="s2")  # same path, different source


def test_database_level_delete_behaviour(connection):
    SQLiteCourseRepository(connection).create_course("c1", "Physics", None, None, None)
    _insert_source(connection, course_id="c1")
    _insert_file(connection)

    connection.execute("DELETE FROM courses WHERE id = 'c1'")
    assert connection.execute("SELECT course_id FROM library_sources").fetchone()[0] is None
    assert connection.execute("SELECT COUNT(*) FROM library_files").fetchone()[0] == 1

    connection.execute("DELETE FROM library_sources WHERE id = 's1'")
    assert connection.execute("SELECT COUNT(*) FROM library_files").fetchone()[0] == 0


# --- v5 -> v6 migration --------------------------------------------------------------


def _create_v5_database(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE courses (id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT, term TEXT, "
        "description TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE chats (id TEXT PRIMARY KEY, title TEXT, "
        "course_id TEXT REFERENCES courses(id) ON DELETE SET NULL, "
        "teaching_mode TEXT NOT NULL DEFAULT 'teach', reasoning_mode TEXT NOT NULL DEFAULT 'fast', "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL "
        "REFERENCES chats(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE learning_memories (id TEXT PRIMARY KEY, course_id TEXT REFERENCES courses(id) ON DELETE SET NULL, "
        "source_chat_id TEXT REFERENCES chats(id) ON DELETE SET NULL, topic TEXT NOT NULL, kind TEXT NOT NULL, "
        "summary TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute("PRAGMA user_version = 5")
    conn.commit()
    return conn


def _seed_v5(conn):
    conn.execute("INSERT INTO courses VALUES ('c1', 'Physics', 'PHY', 'Fall', 'Mechanics', 't1', 't1')")
    conn.execute("INSERT INTO chats VALUES ('chat1', 'Chat', 'c1', 'homework', 'deep', 't2', 't3')")
    conn.execute("INSERT INTO messages (chat_id, role, content, created_at) VALUES ('chat1', 'user', 'hi', 't2')")
    conn.execute("INSERT INTO learning_memories VALUES ('m1', 'c1', 'chat1', 'Vectors', 'needs_review', 'sum', 'active', 't4', 't4')")
    conn.commit()


def test_v5_database_migrates_through_v6_preserving_everything(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v5_database(db_path)
    _seed_v5(seed)
    seed.close()

    connection = open_database(db_path)
    try:
        assert get_schema_version(connection) == SCHEMA_VERSION
        assert connection.execute("SELECT name FROM courses WHERE id = 'c1'").fetchone()[0] == "Physics"
        chat = connection.execute("SELECT * FROM chats WHERE id = 'chat1'").fetchone()
        assert (chat["teaching_mode"], chat["reasoning_mode"], chat["course_id"]) == ("homework", "deep", "c1")
        assert connection.execute("SELECT content FROM messages").fetchone()[0] == "hi"
        assert connection.execute("SELECT summary, status FROM learning_memories").fetchone()[:] == ("sum", "active")
        assert {"library_sources", "library_files"} <= _names(connection, "table")
        assert connection.execute("SELECT COUNT(*) FROM library_sources").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

        # The migrated database is immediately usable for library data.
        repo = SQLiteLibraryRepository(connection)
        source = repo.create_source("s1", "c1", LibrarySourceKind.LOCAL_FOLDER, "Phys", "/x")
        assert source.course_id == "c1"
    finally:
        connection.close()


def test_library_migration_runs_exactly_once(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v5_database(db_path)
    _seed_v5(seed)
    seed.close()

    open_database(db_path).close()
    connection = open_database(db_path)  # reopening must not re-run it (a duplicate CREATE would fail)
    try:
        assert get_schema_version(connection) == SCHEMA_VERSION
        assert connection.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 1
    finally:
        connection.close()


def test_failed_v6_migration_leaves_the_v5_database_untouched(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v5_database(db_path)
    _seed_v5(seed)
    seed.execute("CREATE TABLE library_files (bogus INTEGER)")  # collides with the migration's own table
    seed.commit()
    seed.close()

    with pytest.raises(sqlite3.OperationalError):
        open_database(db_path)

    verify = sqlite3.connect(db_path)
    try:
        assert verify.execute("PRAGMA user_version").fetchone()[0] == 5
        assert "library_sources" not in _names(verify, "table")  # created earlier in the failed transaction, rolled back
        assert verify.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 1
    finally:
        verify.close()


# --- transactions --------------------------------------------------------------------


def test_deleting_a_source_is_all_or_nothing(connection):
    repo = SQLiteLibraryRepository(connection)
    repo.create_source("s1", None, LibrarySourceKind.LOCAL_FOLDER, "n", "/x")
    for index, path in enumerate(["a.pdf", "b.pdf", "c.pdf"]):
        repo.create_file(f"f{index}", "s1", path, path, None, None, None, None)
    connection.execute(
        "CREATE TRIGGER block_b BEFORE DELETE ON library_files WHEN old.relative_path = 'b.pdf' "
        "BEGIN SELECT RAISE(ABORT, 'blocked'); END"
    )

    with pytest.raises(sqlite3.IntegrityError):
        repo.delete_source("s1")

    assert repo.get_source("s1") is not None
    assert len(repo.list_files(source_id="s1")) == 3  # the cascade for a.pdf and c.pdf rolled back too


def test_failed_course_delete_leaves_memories_and_library_links_unchanged(connection):
    courses = CourseService(SQLiteCourseRepository(connection), SQLiteChatRepository(connection))
    course = courses.create_course("Physics")
    memories = SQLiteLearningMemoryRepository(connection)
    memories.create("m1", course.id, None, "Vectors", MemoryKind.NEEDS_REVIEW, "review", MemoryStatus.ACTIVE)
    repo = SQLiteLibraryRepository(connection)
    repo.create_source("s1", course.id, LibrarySourceKind.LOCAL_FOLDER, "n", "/x")
    connection.execute(
        "CREATE TRIGGER block_course_delete BEFORE DELETE ON courses BEGIN SELECT RAISE(ABORT, 'blocked'); END"
    )

    with pytest.raises(sqlite3.IntegrityError):
        courses.delete_course(course.id)

    assert memories.get("m1").status is MemoryStatus.ACTIVE
    assert repo.get_source("s1").course_id == course.id


def test_save_file_changes_only_the_mutable_columns(connection):
    repo = SQLiteLibraryRepository(connection)
    repo.create_source("s1", None, LibrarySourceKind.LOCAL_FOLDER, "n", "/x")
    file = repo.create_file("f1", "s1", "a.pdf", "a.pdf", "pdf", 5, "t", None)

    file.processing_state = LibraryFileState.INDEXING
    saved = repo.save_file(file)

    assert (saved.id, saved.source_id, saved.relative_path, saved.created_at) == ("f1", "s1", "a.pdf", file.created_at)
    assert saved.processing_state is LibraryFileState.INDEXING
