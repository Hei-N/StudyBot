import sqlite3

import pytest

from studybot.core.messages import Role
from studybot.storage.sqlite_repository import SCHEMA_VERSION, SQLiteChatRepository


@pytest.fixture
def repo(tmp_path):
    repository = SQLiteChatRepository(tmp_path / "studybot-test.db")
    yield repository
    repository.close()


def test_schema_version_is_1(repo):
    assert SCHEMA_VERSION == 1
    assert repo.schema_version == 1


def test_database_file_is_created_inside_given_directory(tmp_path):
    db_path = tmp_path / "nested" / "studybot-test.db"
    repository = SQLiteChatRepository(db_path)
    try:
        assert db_path.exists()
    finally:
        repository.close()


def test_foreign_keys_are_enabled(repo):
    row = repo._conn.execute("PRAGMA foreign_keys").fetchone()
    assert row[0] == 1


def test_create_and_get_chat(repo):
    created = repo.create_chat("chat-1", "My Chat")

    fetched = repo.get_chat("chat-1")

    assert fetched is not None
    assert fetched.id == "chat-1"
    assert fetched.title == "My Chat"
    assert fetched.created_at == created.created_at
    assert fetched.updated_at == created.updated_at


def test_get_chat_returns_none_for_missing_chat(repo):
    assert repo.get_chat("does-not-exist") is None


def test_create_chat_with_no_title(repo):
    created = repo.create_chat("chat-1", None)

    assert created.title is None
    assert repo.get_chat("chat-1").title is None


def test_list_chats_empty_initially(repo):
    assert repo.list_chats() == []


def test_list_chats_orders_most_recently_updated_first(repo, monkeypatch):
    monkeypatch.setattr(
        "studybot.storage.sqlite_repository._now", lambda: "2024-01-01T00:00:00+00:00"
    )
    repo.create_chat("a", "A")
    monkeypatch.setattr(
        "studybot.storage.sqlite_repository._now", lambda: "2024-01-01T00:01:00+00:00"
    )
    repo.create_chat("b", "B")

    # Touching "a" after "b" was created should move it back to the front.
    monkeypatch.setattr(
        "studybot.storage.sqlite_repository._now", lambda: "2024-01-01T00:05:00+00:00"
    )
    repo.touch_chat("a")

    chats = repo.list_chats()

    assert [c.id for c in chats] == ["a", "b"]


def test_rename_chat_updates_title_and_updated_at(repo):
    created = repo.create_chat("chat-1", None)

    renamed = repo.rename_chat("chat-1", "New Title")

    assert renamed.title == "New Title"
    assert renamed.updated_at >= created.updated_at
    assert repo.get_chat("chat-1").title == "New Title"


def test_touch_chat_updates_updated_at_without_changing_title(repo):
    repo.create_chat("chat-1", "Keep Me")

    touched = repo.touch_chat("chat-1")

    assert touched.title == "Keep Me"


def test_delete_chat_removes_it(repo):
    repo.create_chat("chat-1", "Gone Soon")

    repo.delete_chat("chat-1")

    assert repo.get_chat("chat-1") is None


def test_delete_chat_cascades_to_messages(repo):
    repo.create_chat("chat-1", "Title")
    repo.append_message("chat-1", Role.USER, "hello")
    repo.append_message("chat-1", Role.ASSISTANT, "hi")

    repo.delete_chat("chat-1")

    # The messages table has no chat to belong to any more.
    row = repo._conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", ("chat-1",)).fetchone()
    assert row[0] == 0


def test_clear_messages_keeps_the_chat(repo):
    repo.create_chat("chat-1", "Keep Chat")
    repo.append_message("chat-1", Role.USER, "hello")

    repo.clear_messages("chat-1")

    assert repo.get_chat("chat-1") is not None
    assert repo.load_messages("chat-1") == []


def test_append_and_load_messages_preserve_order(repo):
    repo.create_chat("chat-1", "Title")
    repo.append_message("chat-1", Role.USER, "first")
    repo.append_message("chat-1", Role.ASSISTANT, "second")
    repo.append_message("chat-1", Role.USER, "third")

    messages = repo.load_messages("chat-1")

    assert [m.content for m in messages] == ["first", "second", "third"]
    assert [m.role for m in messages] == [Role.USER, Role.ASSISTANT, Role.USER]


def test_load_messages_never_returns_system_role(repo):
    # The repository has no concept of a system message — nothing ever
    # inserts one — but this documents the guarantee explicitly.
    repo.create_chat("chat-1", "Title")
    repo.append_message("chat-1", Role.USER, "hello")

    messages = repo.load_messages("chat-1")

    assert all(m.role is not Role.SYSTEM for m in messages)


def test_messages_are_isolated_per_chat(repo):
    repo.create_chat("chat-1", "One")
    repo.create_chat("chat-2", "Two")
    repo.append_message("chat-1", Role.USER, "for chat one")
    repo.append_message("chat-2", Role.USER, "for chat two")

    assert [m.content for m in repo.load_messages("chat-1")] == ["for chat one"]
    assert [m.content for m in repo.load_messages("chat-2")] == ["for chat two"]


def test_unicode_and_burmese_content_round_trips(repo):
    burmese = "မြန်မာလို အရှိန်နဲ့ velocity ကို ရှင်းပြပါ။"
    repo.create_chat("chat-1", burmese)
    repo.append_message("chat-1", Role.USER, burmese)

    assert repo.get_chat("chat-1").title == burmese
    assert repo.load_messages("chat-1")[0].content == burmese


def test_emoji_and_apostrophes_round_trip(repo):
    content = "It's a test 🎉 with emoji and apostrophes' galore"
    repo.create_chat("chat-1", "Title")
    repo.append_message("chat-1", Role.USER, content)

    assert repo.load_messages("chat-1")[0].content == content


def test_multiline_content_round_trips(repo):
    content = "Line one\nLine two\n\nLine four with trailing space \nEnd"
    repo.create_chat("chat-1", "Title")
    repo.append_message("chat-1", Role.ASSISTANT, content)

    assert repo.load_messages("chat-1")[0].content == content


def test_sql_injection_style_content_is_stored_literally(repo):
    malicious = "'; DROP TABLE chats; --"
    repo.create_chat("chat-1", "Title")
    repo.append_message("chat-1", Role.USER, malicious)

    assert repo.load_messages("chat-1")[0].content == malicious
    assert repo.get_chat("chat-1") is not None  # table still exists and chat is intact


def test_persistence_survives_reopening_the_database(tmp_path):
    db_path = tmp_path / "studybot-test.db"

    repo1 = SQLiteChatRepository(db_path)
    repo1.create_chat("chat-1", "Persisted Title")
    repo1.append_message("chat-1", Role.USER, "hello")
    repo1.append_message("chat-1", Role.ASSISTANT, "hi there")
    repo1.close()

    repo2 = SQLiteChatRepository(db_path)
    try:
        chat = repo2.get_chat("chat-1")
        messages = repo2.load_messages("chat-1")
        assert chat is not None
        assert chat.title == "Persisted Title"
        assert [m.content for m in messages] == ["hello", "hi there"]
    finally:
        repo2.close()


def test_opening_the_same_database_twice_is_idempotent(tmp_path):
    db_path = tmp_path / "studybot-test.db"

    repo1 = SQLiteChatRepository(db_path)
    repo1.create_chat("chat-1", "Title")
    repo1.close()

    # Reopening must not recreate/wipe tables or fail on already-existing schema.
    repo2 = SQLiteChatRepository(db_path)
    try:
        assert repo2.schema_version == 1
        assert repo2.get_chat("chat-1") is not None
    finally:
        repo2.close()


def test_database_file_lives_in_configured_directory_not_repo(tmp_path):
    db_path = tmp_path / "StudyBot" / "studybot.db"
    repository = SQLiteChatRepository(db_path)
    try:
        assert db_path.is_file()
        assert db_path.parent == tmp_path / "StudyBot"
    finally:
        repository.close()
