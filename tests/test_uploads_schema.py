import sqlite3

import pytest

from studybot.storage import database
from studybot.storage.database import SCHEMA_VERSION, get_schema_version, open_database


def build_v8(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    for statement in (
        *database._FRESH_SCHEMA_STATEMENTS,
        *database._LIBRARY_SCHEMA_STATEMENTS,
        *database._LIBRARY_AUTHORIZATION_STATEMENTS,
        *database._LIBRARY_PAGE_STATEMENTS,
    ):
        conn.execute(statement)
    conn.execute("INSERT INTO courses VALUES ('c1', 'Physics', NULL, NULL, NULL, 't', 't')")
    conn.execute("INSERT INTO chats VALUES ('chat1', 'Chat', 'c1', 'homework', 'deep', 't', 't')")
    conn.execute("INSERT INTO messages (chat_id, role, content, created_at) VALUES ('chat1', 'user', 'hi', 't')")
    conn.execute("INSERT INTO library_sources VALUES ('s1', 'c1', 'local_folder', 'Phys', '/x', 't', 't')")
    conn.execute("INSERT INTO library_source_authorizations VALUES ('s1', 'macos', 'security_scoped_bookmark', x'01', 't', 't')")
    conn.execute(
        "INSERT INTO library_files (id, source_id, relative_path, display_name, processing_state, content_hash, "
        "page_count, text_page_count, processing_version, created_at, updated_at) "
        "VALUES ('f1', 's1', 'a.pdf', 'a', 'ready', ?, 1, 1, 'pdf_text_v1', 't', 't')",
        ("a" * 64,),
    )
    conn.execute("INSERT INTO library_pages VALUES ('f1', 1, 'page text', 9, 't', 't')")
    conn.execute("PRAGMA user_version = 8")
    conn.commit()
    return conn


def test_v8_database_migrates_to_v9_preserving_everything(tmp_path):
    db_path = tmp_path / "studybot.db"
    build_v8(db_path).close()

    connection = open_database(db_path)
    try:
        assert get_schema_version(connection) == SCHEMA_VERSION == 9
        assert connection.execute("SELECT content FROM messages").fetchone()[0] == "hi"
        source = connection.execute("SELECT * FROM library_sources").fetchone()
        assert (source["id"], source["course_id"], source["kind"], source["locator"]) == ("s1", "c1", "local_folder", "/x")
        assert connection.execute("SELECT text_content FROM library_pages").fetchone()[0] == "page text"
        assert connection.execute("SELECT COUNT(*) FROM library_source_authorizations").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1  # switched back on
    finally:
        connection.close()


def test_the_rebuilt_table_keeps_its_relationships_and_allows_uploads(tmp_path):
    db_path = tmp_path / "studybot.db"
    build_v8(db_path).close()
    connection = open_database(db_path)
    try:
        connection.execute("INSERT INTO library_sources VALUES ('u1', NULL, 'uploads', 'Uploaded files', 'studybot:uploads', 't', 't')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO library_sources VALUES ('x', NULL, 'dropbox', 'n', '/y', 't', 't')")
        with pytest.raises(sqlite3.IntegrityError):  # (kind, locator) is still unique
            connection.execute("INSERT INTO library_sources VALUES ('u2', NULL, 'uploads', 'n', 'studybot:uploads', 't', 't')")
        indexes = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert "idx_library_sources_course_id" in indexes
        # children still cascade from the rebuilt parent, and the course link still clears
        connection.execute("DELETE FROM courses WHERE id = 'c1'")
        assert connection.execute("SELECT course_id FROM library_sources WHERE id = 's1'").fetchone()[0] is None
        connection.execute("DELETE FROM library_sources WHERE id = 's1'")
        assert connection.execute("SELECT COUNT(*) FROM library_files").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM library_pages").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM library_source_authorizations").fetchone()[0] == 0
    finally:
        connection.close()


def test_a_fresh_database_has_the_same_shape(tmp_path):
    connection = open_database(tmp_path / "fresh.db")
    try:
        assert get_schema_version(connection) == 9
        connection.execute("INSERT INTO library_sources VALUES ('u1', NULL, 'uploads', 'n', 'studybot:uploads', 't', 't')")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert {"library_pages", "library_source_authorizations"} <= {
            r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        connection.close()


def test_migration_runs_once(tmp_path):
    db_path = tmp_path / "studybot.db"
    build_v8(db_path).close()
    open_database(db_path).close()

    again = open_database(db_path)
    assert get_schema_version(again) == 9
    again.close()


def test_a_failed_v9_migration_rolls_back_and_restores_foreign_keys(tmp_path, monkeypatch):
    db_path = tmp_path / "studybot.db"
    seed = build_v8(db_path)
    seed.execute("CREATE TABLE library_sources_new (bogus INTEGER)")  # collides with the migration's temp table
    seed.commit()
    seed.close()

    with pytest.raises(sqlite3.OperationalError):
        open_database(db_path)

    verify = sqlite3.connect(db_path)
    try:
        assert verify.execute("PRAGMA user_version").fetchone()[0] == 8
        assert verify.execute("SELECT kind FROM library_sources").fetchone()[0] == "local_folder"
        assert verify.execute("SELECT COUNT(*) FROM library_pages").fetchone()[0] == 1
    finally:
        verify.close()


def test_foreign_keys_stay_on_after_a_failed_migration(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = build_v8(db_path)
    seed.execute("CREATE TABLE library_sources_new (bogus INTEGER)")
    seed.commit()
    seed.close()
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.OperationalError):
        database._migrate_v8_to_v9(connection)
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    connection.close()
