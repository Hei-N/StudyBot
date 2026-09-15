import pytest

from studybot.core.messages import Role
from studybot.core.teaching_mode import TeachingMode
from studybot.storage.database import open_database
from studybot.storage.sqlite_repository import SQLiteChatRepository


@pytest.fixture
def connection(tmp_path):
    conn = open_database(tmp_path / "studybot-test.db")
    yield conn
    conn.close()


@pytest.fixture
def repo(connection):
    return SQLiteChatRepository(connection)


def test_foreign_keys_are_enabled(connection):
    row = connection.execute("PRAGMA foreign_keys").fetchone()
    assert row[0] == 1


def test_create_and_get_chat(repo):
    created = repo.create_chat("chat-1", "My Chat")

    fetched = repo.get_chat("chat-1")

    assert fetched is not None
    assert fetched.id == "chat-1"
    assert fetched.title == "My Chat"
    assert fetched.course_id is None
    assert fetched.teaching_mode is TeachingMode.TEACH
    assert fetched.created_at == created.created_at
    assert fetched.updated_at == created.updated_at


def test_create_chat_with_course(repo, connection):
    connection.execute(
        "INSERT INTO courses (id, name, created_at, updated_at) VALUES ('c1', 'Physics', 't', 't')"
    )

    created = repo.create_chat("chat-1", "Title", course_id="c1")

    assert created.course_id == "c1"
    assert repo.get_chat("chat-1").course_id == "c1"


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


def test_delete_chat_cascades_to_messages(repo, connection):
    repo.create_chat("chat-1", "Title")
    repo.append_message("chat-1", Role.USER, "hello")
    repo.append_message("chat-1", Role.ASSISTANT, "hi")

    repo.delete_chat("chat-1")

    # The messages table has no chat to belong to any more.
    row = connection.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", ("chat-1",)).fetchone()
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


# --- course relationship ------------------------------------------------------------


def test_list_chats_by_course_filters_correctly(repo, connection):
    connection.execute(
        "INSERT INTO courses (id, name, created_at, updated_at) VALUES ('c1', 'Physics', 't', 't')"
    )
    repo.create_chat("chat-1", "In course", course_id="c1")
    repo.create_chat("chat-2", "General chat", course_id=None)

    assert [c.id for c in repo.list_chats_by_course("c1")] == ["chat-1"]
    assert [c.id for c in repo.list_chats_by_course(None)] == ["chat-2"]


def test_move_chat_to_course_preserves_messages_and_title(repo, connection):
    connection.execute(
        "INSERT INTO courses (id, name, created_at, updated_at) VALUES ('c1', 'Physics', 't', 't')"
    )
    repo.create_chat("chat-1", "My Chat")
    repo.append_message("chat-1", Role.USER, "hello")

    moved = repo.move_chat_to_course("chat-1", "c1")

    assert moved.course_id == "c1"
    assert moved.id == "chat-1"
    assert moved.title == "My Chat"
    assert [m.content for m in repo.load_messages("chat-1")] == ["hello"]


def test_move_chat_to_course_none_unassigns(repo, connection):
    connection.execute(
        "INSERT INTO courses (id, name, created_at, updated_at) VALUES ('c1', 'Physics', 't', 't')"
    )
    repo.create_chat("chat-1", "Title", course_id="c1")

    moved = repo.move_chat_to_course("chat-1", None)

    assert moved.course_id is None


def test_deleting_course_sets_chat_course_id_null_and_preserves_chat(repo, connection):
    connection.execute(
        "INSERT INTO courses (id, name, created_at, updated_at) VALUES ('c1', 'Physics', 't', 't')"
    )
    repo.create_chat("chat-1", "Title", course_id="c1")
    repo.append_message("chat-1", Role.USER, "hello")

    connection.execute("DELETE FROM courses WHERE id = 'c1'")
    connection.commit()

    chat = repo.get_chat("chat-1")
    assert chat is not None
    assert chat.course_id is None
    assert [m.content for m in repo.load_messages("chat-1")] == ["hello"]


def test_count_chats_for_course(repo, connection):
    connection.execute(
        "INSERT INTO courses (id, name, created_at, updated_at) VALUES ('c1', 'Physics', 't', 't')"
    )
    repo.create_chat("chat-1", "A", course_id="c1")
    repo.create_chat("chat-2", "B", course_id="c1")
    repo.create_chat("chat-3", "C", course_id=None)

    assert repo.count_chats_for_course("c1") == 2


# --- teaching mode -------------------------------------------------------------------


def test_create_chat_with_explicit_teaching_mode(repo):
    created = repo.create_chat("chat-1", "Title", teaching_mode=TeachingMode.EXAM)

    assert created.teaching_mode is TeachingMode.EXAM
    assert repo.get_chat("chat-1").teaching_mode is TeachingMode.EXAM


def test_set_teaching_mode_updates_and_bumps_updated_at(repo):
    created = repo.create_chat("chat-1", "Title")

    updated = repo.set_teaching_mode("chat-1", TeachingMode.HOMEWORK)

    assert updated.teaching_mode is TeachingMode.HOMEWORK
    assert updated.updated_at >= created.updated_at
    assert repo.get_chat("chat-1").teaching_mode is TeachingMode.HOMEWORK


def test_set_teaching_mode_does_not_touch_title_or_course(repo, connection):
    connection.execute(
        "INSERT INTO courses (id, name, created_at, updated_at) VALUES ('c1', 'Physics', 't', 't')"
    )
    repo.create_chat("chat-1", "Keep Me", course_id="c1")

    repo.set_teaching_mode("chat-1", TeachingMode.PRACTICE)

    chat = repo.get_chat("chat-1")
    assert chat.title == "Keep Me"
    assert chat.course_id == "c1"


def test_set_teaching_mode_does_not_touch_messages(repo):
    repo.create_chat("chat-1", "Title")
    repo.append_message("chat-1", Role.USER, "hello")

    repo.set_teaching_mode("chat-1", TeachingMode.QUICK)

    assert [m.content for m in repo.load_messages("chat-1")] == ["hello"]


def test_moving_chat_between_courses_preserves_teaching_mode(repo, connection):
    connection.execute(
        "INSERT INTO courses (id, name, created_at, updated_at) VALUES ('c1', 'Physics', 't', 't')"
    )
    repo.create_chat("chat-1", "Title", teaching_mode=TeachingMode.EXAM)

    repo.move_chat_to_course("chat-1", "c1")

    assert repo.get_chat("chat-1").teaching_mode is TeachingMode.EXAM


def test_deleting_course_preserves_chat_teaching_mode(repo, connection):
    connection.execute(
        "INSERT INTO courses (id, name, created_at, updated_at) VALUES ('c1', 'Physics', 't', 't')"
    )
    repo.create_chat("chat-1", "Title", course_id="c1", teaching_mode=TeachingMode.PRACTICE)

    connection.execute("DELETE FROM courses WHERE id = 'c1'")
    connection.commit()

    assert repo.get_chat("chat-1").teaching_mode is TeachingMode.PRACTICE


def test_renaming_chat_preserves_teaching_mode(repo):
    repo.create_chat("chat-1", "Old Title", teaching_mode=TeachingMode.HOMEWORK)

    repo.rename_chat("chat-1", "New Title")

    assert repo.get_chat("chat-1").teaching_mode is TeachingMode.HOMEWORK


def test_clearing_messages_preserves_teaching_mode(repo):
    repo.create_chat("chat-1", "Title", teaching_mode=TeachingMode.EXAM)
    repo.append_message("chat-1", Role.USER, "hello")

    repo.clear_messages("chat-1")

    assert repo.get_chat("chat-1").teaching_mode is TeachingMode.EXAM


def test_invalid_stored_mode_falls_back_to_default(repo, connection):
    repo.create_chat("chat-1", "Title")
    # Simulate a corrupted/tampered value bypassing the repository API.
    connection.execute("UPDATE chats SET teaching_mode = 'not-a-real-mode' WHERE id = 'chat-1'")
    connection.commit()

    chat = repo.get_chat("chat-1")

    assert chat.teaching_mode is TeachingMode.TEACH  # deliberate, documented fallback
