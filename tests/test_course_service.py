import pytest

from studybot.core.course_service import CourseService
from studybot.core.exceptions import SessionError
from studybot.storage.database import open_database
from studybot.storage.sqlite_course_repository import SQLiteCourseRepository
from studybot.storage.sqlite_repository import SQLiteChatRepository


@pytest.fixture
def connection(tmp_path):
    conn = open_database(tmp_path / "studybot-test.db")
    yield conn
    conn.close()


@pytest.fixture
def service(connection):
    return CourseService(
        course_repository=SQLiteCourseRepository(connection),
        chat_repository=SQLiteChatRepository(connection),
    )


def test_create_course_trims_and_stores_fields(service):
    course = service.create_course("  University Physics I  ", " PHY 215 ", " Fall 2026 ", "  desc  ")

    assert course.name == "University Physics I"
    assert course.code == "PHY 215"
    assert course.term == "Fall 2026"
    assert course.description == "desc"


def test_create_course_with_only_a_name(service):
    course = service.create_course("Calculus III")

    assert course.code is None
    assert course.term is None
    assert course.description is None


def test_create_course_rejects_empty_name(service):
    with pytest.raises(SessionError):
        service.create_course("")


def test_create_course_rejects_whitespace_only_name(service):
    with pytest.raises(SessionError):
        service.create_course("   \n\t  ")


def test_create_course_collapses_internal_whitespace_in_name(service):
    course = service.create_course("University   Physics\nI")

    assert course.name == "University Physics I"


def test_create_course_rejects_overly_long_name(service):
    with pytest.raises(SessionError):
        service.create_course("x" * 500)


def test_blank_optional_fields_become_none(service):
    course = service.create_course("Title", code="   ", term="", description="   ")

    assert course.code is None
    assert course.term is None
    assert course.description is None


def test_multiline_description_is_preserved(service):
    description = "Line one\nLine two"
    course = service.create_course("Title", description=description)

    assert course.description == description


def test_unicode_names_are_accepted(service):
    for name in ["大学物理", "ရူပဗေဒ", "Physics ⚛️", "It's Physics"]:
        course = service.create_course(name)
        assert course.name == name


def test_list_courses_reflects_repository(service):
    service.create_course("A")
    service.create_course("B")

    assert len(service.list_courses()) == 2


def test_get_course_returns_none_for_missing(service):
    assert service.get_course("nope") is None


def test_resolve_course_by_exact_id(service):
    course = service.create_course("A")

    assert service.resolve_course(course.id).id == course.id


def test_resolve_course_by_unique_prefix(service):
    course = service.create_course("A")

    assert service.resolve_course(course.id[:8]).id == course.id


def test_resolve_course_raises_for_unknown_id(service):
    with pytest.raises(SessionError):
        service.resolve_course("does-not-exist")


def test_resolve_course_raises_for_ambiguous_prefix(service, monkeypatch):
    ids = iter(["abc111-one", "abc222-two"])
    monkeypatch.setattr("uuid.uuid4", lambda: next(ids))
    service.create_course("A")
    service.create_course("B")

    with pytest.raises(SessionError):
        service.resolve_course("abc")


def test_edit_course_updates_fields(service):
    course = service.create_course("Old", "OLD", "Spring", "old")

    updated = service.edit_course(course.id, "New", "NEW", "Fall", "new")

    assert updated.name == "New"
    assert updated.code == "NEW"
    assert updated.term == "Fall"
    assert updated.description == "new"


def test_edit_course_can_clear_optional_fields(service):
    course = service.create_course("Title", "CODE", "Term", "Desc")

    updated = service.edit_course(course.id, "Title", None, None, None)

    assert updated.code is None
    assert updated.term is None
    assert updated.description is None


def test_edit_course_rejects_empty_name(service):
    course = service.create_course("Title")

    with pytest.raises(SessionError):
        service.edit_course(course.id, "   ", None, None, None)


def test_delete_course_removes_it_and_returns_it(service):
    course = service.create_course("Doomed")

    deleted = service.delete_course(course.id)

    assert deleted.id == course.id
    assert service.get_course(course.id) is None


def test_delete_course_raises_for_missing_course(service):
    with pytest.raises(SessionError):
        service.delete_course("does-not-exist")


def test_count_chats_for_course_starts_at_zero(service):
    course = service.create_course("Title")

    assert service.count_chats(course.id) == 0
