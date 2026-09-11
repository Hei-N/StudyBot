import pytest

from studybot.storage.database import open_database
from studybot.storage.sqlite_course_repository import SQLiteCourseRepository


@pytest.fixture
def connection(tmp_path):
    conn = open_database(tmp_path / "studybot-test.db")
    yield conn
    conn.close()


@pytest.fixture
def repo(connection):
    return SQLiteCourseRepository(connection)


def test_create_and_get_course(repo):
    created = repo.create_course("c1", "University Physics I", "PHY 215", "Fall 2026", "Mechanics")

    fetched = repo.get_course("c1")

    assert fetched is not None
    assert fetched.id == "c1"
    assert fetched.name == "University Physics I"
    assert fetched.code == "PHY 215"
    assert fetched.term == "Fall 2026"
    assert fetched.description == "Mechanics"
    assert fetched.created_at == created.created_at
    assert fetched.updated_at == created.updated_at


def test_create_course_with_only_required_fields(repo):
    created = repo.create_course("c1", "Calculus III", None, None, None)

    assert created.code is None
    assert created.term is None
    assert created.description is None


def test_get_course_returns_none_for_missing_course(repo):
    assert repo.get_course("does-not-exist") is None


def test_list_courses_empty_initially(repo):
    assert repo.list_courses() == []


def test_list_courses_orders_most_recently_updated_first(repo, monkeypatch):
    monkeypatch.setattr(
        "studybot.storage.sqlite_course_repository._now", lambda: "2024-01-01T00:00:00+00:00"
    )
    repo.create_course("a", "A", None, None, None)
    monkeypatch.setattr(
        "studybot.storage.sqlite_course_repository._now", lambda: "2024-01-01T00:01:00+00:00"
    )
    repo.create_course("b", "B", None, None, None)

    monkeypatch.setattr(
        "studybot.storage.sqlite_course_repository._now", lambda: "2024-01-01T00:05:00+00:00"
    )
    repo.update_course("a", "A", None, None, None)

    courses = repo.list_courses()

    assert [c.id for c in courses] == ["a", "b"]


def test_update_course_replaces_all_editable_fields(repo):
    created = repo.create_course("c1", "Old Name", "OLD", "Spring", "old desc")

    updated = repo.update_course("c1", "New Name", "NEW", "Fall", "new desc")

    assert updated.name == "New Name"
    assert updated.code == "NEW"
    assert updated.term == "Fall"
    assert updated.description == "new desc"
    assert updated.updated_at >= created.updated_at


def test_update_course_can_clear_optional_fields(repo):
    repo.create_course("c1", "Name", "CODE", "Term", "Description")

    updated = repo.update_course("c1", "Name", None, None, None)

    assert updated.code is None
    assert updated.term is None
    assert updated.description is None


def test_delete_course_removes_it(repo):
    repo.create_course("c1", "Gone Soon", None, None, None)

    repo.delete_course("c1")

    assert repo.get_course("c1") is None


def test_unicode_chinese_and_burmese_names_round_trip(repo):
    chinese = repo.create_course("c1", "大学物理", None, None, None)
    burmese = repo.create_course("c2", "ရူပဗေဒ", None, None, None)

    assert repo.get_course("c1").name == chinese.name
    assert repo.get_course("c2").name == burmese.name


def test_emoji_and_apostrophes_in_name_round_trip(repo):
    name = "Physics ⚛️ — It's Great!"
    repo.create_course("c1", name, None, None, None)

    assert repo.get_course("c1").name == name


def test_multiline_description_round_trips(repo):
    description = "Line one\nLine two\n\nLine four"
    repo.create_course("c1", "Title", None, None, description)

    assert repo.get_course("c1").description == description


def test_sql_injection_style_content_is_stored_literally(repo):
    malicious = "'; DROP TABLE courses; --"
    repo.create_course("c1", malicious, None, None, None)

    assert repo.get_course("c1").name == malicious
