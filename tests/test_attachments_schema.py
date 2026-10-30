import sqlite3

import pytest

from studybot.storage import database
from studybot.storage.database import SCHEMA_VERSION, get_schema_version, open_database


def build_v9(path):
    """A real v9 database: the current schema with the v10 additions taken back out."""
    conn = open_database(path)
    conn.execute("DROP TABLE message_attachments")
    conn.execute("ALTER TABLE library_files DROP COLUMN in_library")
    conn.execute("PRAGMA user_version = 9")
    conn.execute("INSERT INTO courses VALUES ('c1', 'Physics', NULL, NULL, NULL, 't', 't')")
    conn.execute("INSERT INTO chats VALUES ('chat1', 'Chat', 'c1', 'homework', 'deep', 't', 't')")
    conn.execute("INSERT INTO messages (chat_id, role, content, created_at) VALUES ('chat1', 'user', 'hi', 't')")
    conn.execute("INSERT INTO library_sources VALUES ('s1', 'c1', 'local_folder', 'Phys', '/x', 't', 't')")
    conn.execute("INSERT INTO library_sources VALUES ('u1', NULL, 'uploads', 'Uploaded files', 'studybot:uploads', 't', 't')")
    conn.execute(
        "INSERT INTO library_files (id, source_id, relative_path, display_name, processing_state, content_hash, "
        "page_count, text_page_count, processing_version, created_at, updated_at) "
        "VALUES ('f1', 'u1', 'a.pdf', 'a', 'ready', ?, 1, 1, 'pdf_text_v2', 't', 't')",
        ("a" * 64,),
    )
    conn.execute("INSERT INTO library_pages VALUES ('f1', 1, 'page text', 9, 't', 't')")
    conn.commit()
    return conn


def test_v9_database_migrates_to_v10_keeping_files_in_the_library(tmp_path):
    db_path = tmp_path / "studybot.db"
    build_v9(db_path).close()
    before = sqlite3.connect(db_path)
    assert get_schema_version(before) == 9
    before.close()

    connection = open_database(db_path)
    try:
        assert get_schema_version(connection) == SCHEMA_VERSION == 10
        assert connection.execute("SELECT in_library FROM library_files WHERE id = 'f1'").fetchone()[0] == 1
        assert connection.execute("SELECT content FROM messages").fetchone()[0] == "hi"
        assert connection.execute("SELECT text_content FROM library_pages").fetchone()[0] == "page text"
        assert connection.execute("SELECT COUNT(*) FROM message_attachments").fetchone()[0] == 0  # none invented
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
    again = open_database(db_path)
    assert get_schema_version(again) == 10  # runs once
    again.close()


def test_a_failed_v10_migration_rolls_back(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = build_v9(db_path)
    seed.execute("CREATE TABLE message_attachments (bogus INTEGER)")
    seed.commit()
    seed.close()

    with pytest.raises(sqlite3.OperationalError):
        open_database(db_path)

    verify = sqlite3.connect(db_path)
    try:
        assert verify.execute("PRAGMA user_version").fetchone()[0] == 9
        assert "in_library" not in {r[1] for r in verify.execute("PRAGMA table_info(library_files)")}
    finally:
        verify.close()


def test_the_attachment_table_enforces_its_rules(tmp_path):
    connection = open_database(tmp_path / "fresh.db")
    try:
        assert get_schema_version(connection) == 10
        connection.execute("INSERT INTO chats VALUES ('c', 'C', NULL, 'teach', 'fast', 't', 't')")
        connection.execute("INSERT INTO messages (chat_id, role, content, created_at) VALUES ('c', 'user', 'x', 't')")
        connection.execute("INSERT INTO library_sources VALUES ('u', NULL, 'uploads', 'n', 'studybot:uploads', 't', 't')")
        connection.execute(
            "INSERT INTO library_files (id, source_id, relative_path, display_name, created_at, updated_at) "
            "VALUES ('f', 'u', 'a.pdf', 'a', 't', 't')"
        )
        connection.execute("INSERT INTO message_attachments (message_id, file_id, created_at) VALUES (1, 'f', 't')")
        with pytest.raises(sqlite3.IntegrityError):  # one row per message and file
            connection.execute("INSERT INTO message_attachments (message_id, file_id, created_at) VALUES (1, 'f', 't')")
        with pytest.raises(sqlite3.IntegrityError):  # an attached file cannot be deleted
            connection.execute("DELETE FROM library_files WHERE id = 'f'")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE library_files SET in_library = 2 WHERE id = 'f'")
        connection.execute("DELETE FROM messages WHERE id = 1")  # deleting the message drops the relationship
        assert connection.execute("SELECT COUNT(*) FROM message_attachments").fetchone()[0] == 0
        connection.execute("DELETE FROM library_files WHERE id = 'f'")  # now free to go
    finally:
        connection.close()
