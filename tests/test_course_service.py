import pytest

from studybot.core.course_service import CourseService
from studybot.core.exceptions import SessionError
from studybot.core.learning_memory import MemoryKind, MemoryStatus
from studybot.storage.database import open_database
from studybot.storage.sqlite_course_repository import SQLiteCourseRepository
from studybot.storage.sqlite_learning_memory_repository import SQLiteLearningMemoryRepository
from studybot.storage.sqlite_repository import SQLiteChatRepository


@pytest.fixture
def connection(tmp_path):
    conn = open_database(tmp_path / "studybot-test.db")
    yield conn
    conn.close()


@pytest.fixture
def memory_repository(connection):
    return SQLiteLearningMemoryRepository(connection)


@pytest.fixture
def service(connection):
    return CourseService(
        course_repository=SQLiteCourseRepository(connection),
        chat_repository=SQLiteChatRepository(connection),
    )


@pytest.fixture
def service_with_memory(connection, memory_repository):
    return CourseService(
        course_repository=SQLiteCourseRepository(connection),
        chat_repository=SQLiteChatRepository(connection),
        memory_repository=memory_repository,
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


# =====================================================================================
# Stage 6.1 — deleting a course archives its memories instead of leaking them global
# =====================================================================================


def test_delete_course_without_memory_repository_still_works(service):
    """Backward compatible: a `CourseService` built without a
    `memory_repository` (the default) skips the archiving step entirely
    rather than erroring — nothing in this stage requires every caller to
    know about learning memory."""
    course = service.create_course("Doomed")

    deleted = service.delete_course(course.id)

    assert deleted.id == course.id


def test_delete_course_archives_its_active_memories(service_with_memory, memory_repository):
    course = service_with_memory.create_course("Physics")
    memory = memory_repository.create(
        "mem-1", course.id, None, "Vector components", MemoryKind.NEEDS_REVIEW, "Mixes x/y."
    )

    service_with_memory.delete_course(course.id)

    survived = memory_repository.get(memory.id)
    assert survived is not None
    assert survived.status is MemoryStatus.ARCHIVED
    assert survived.course_id is None  # ON DELETE SET NULL, unchanged
    assert survived.topic == "Vector components"  # content untouched


def test_delete_course_does_not_archive_already_archived_memories_differently(service_with_memory, memory_repository):
    """An already-archived memory in the doomed course stays archived
    (obviously) and isn't touched in a way that would, say, reset its
    `updated_at` unnecessarily — `archive_for_course` only targets active
    rows."""
    course = service_with_memory.create_course("Physics")
    memory = memory_repository.create("mem-1", course.id, None, "Topic", MemoryKind.LEARNING_GOAL, "s")
    memory_repository.archive(memory.id)
    before = memory_repository.get(memory.id).updated_at

    service_with_memory.delete_course(course.id)

    after = memory_repository.get(memory.id)
    assert after.status is MemoryStatus.ARCHIVED
    assert after.updated_at == before


def test_delete_course_never_touches_memories_already_global(service_with_memory, memory_repository):
    course = service_with_memory.create_course("Physics")
    global_memory = memory_repository.create("mem-global", None, None, "Study habits", MemoryKind.USEFUL_STRATEGY, "s")

    service_with_memory.delete_course(course.id)

    still_active = memory_repository.get(global_memory.id)
    assert still_active.status is MemoryStatus.ACTIVE  # never archived — it was never in the deleted course


def test_delete_course_never_touches_memories_in_a_different_course(service_with_memory, memory_repository):
    physics = service_with_memory.create_course("Physics")
    calculus = service_with_memory.create_course("Calculus")
    calc_memory = memory_repository.create("mem-calc", calculus.id, None, "Derivatives", MemoryKind.NEEDS_REVIEW, "s")

    service_with_memory.delete_course(physics.id)

    untouched = memory_repository.get(calc_memory.id)
    assert untouched.status is MemoryStatus.ACTIVE
    assert untouched.course_id == calculus.id


def test_orphaned_memory_remains_editable_after_course_deletion(service_with_memory, memory_repository):
    course = service_with_memory.create_course("Physics")
    memory = memory_repository.create("mem-1", course.id, None, "Vectors", MemoryKind.NEEDS_REVIEW, "s")

    service_with_memory.delete_course(course.id)

    edited = memory_repository.update(memory.id, topic="Vector components (reviewed)")
    assert edited.topic == "Vector components (reviewed)"
    assert edited.status is MemoryStatus.ARCHIVED  # editing alone does not reactivate it


def test_orphaned_memory_can_be_explicitly_restored_to_active_global(service_with_memory, memory_repository):
    course = service_with_memory.create_course("Physics")
    memory = memory_repository.create("mem-1", course.id, None, "Vectors", MemoryKind.NEEDS_REVIEW, "s")

    service_with_memory.delete_course(course.id)
    restored = memory_repository.restore(memory.id)

    assert restored.status is MemoryStatus.ACTIVE
    assert restored.course_id is None  # explicit choice: now global, not silently


def test_orphaned_memory_can_be_explicitly_reassigned_to_a_different_course(service_with_memory, memory_repository):
    physics = service_with_memory.create_course("Physics")
    calculus = service_with_memory.create_course("Calculus")
    memory = memory_repository.create("mem-1", physics.id, None, "Related topic", MemoryKind.LEARNING_GOAL, "s")

    service_with_memory.delete_course(physics.id)
    reassigned = memory_repository.update(memory.id, course_id=calculus.id)
    restored = memory_repository.restore(memory.id)

    assert restored.course_id == calculus.id
    assert restored.status is MemoryStatus.ACTIVE
    assert reassigned.course_id == calculus.id  # the reassignment itself is independent of restore ordering


def test_delete_course_with_no_memories_at_all_does_not_error(service_with_memory):
    course = service_with_memory.create_course("Empty Course")

    deleted = service_with_memory.delete_course(course.id)

    assert deleted.id == course.id
