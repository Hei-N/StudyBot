import pytest

from studybot.core.learning_memory import MemoryKind, MemoryStatus
from studybot.storage.base import UNSET
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
def repository(connection):
    return SQLiteLearningMemoryRepository(connection)


@pytest.fixture
def chat_repository(connection):
    return SQLiteChatRepository(connection)


@pytest.fixture
def course_repository(connection):
    return SQLiteCourseRepository(connection)


def make(repository, memory_id="mem-1", course_id=None, source_chat_id=None, topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="Mixes x/y."):
    return repository.create(memory_id, course_id, source_chat_id, topic, kind, summary)


# --- create / get --------------------------------------------------------------------


def test_create_returns_memory_with_timestamps(repository):
    memory = make(repository)

    assert memory.id == "mem-1"
    assert memory.topic == "Vectors"
    assert memory.kind is MemoryKind.NEEDS_REVIEW
    assert memory.status is MemoryStatus.ACTIVE  # default
    assert memory.created_at
    assert memory.updated_at


def test_create_persists_the_row(repository):
    make(repository)

    fetched = repository.get("mem-1")
    assert fetched is not None
    assert fetched.topic == "Vectors"


def test_get_returns_none_for_unknown_id(repository):
    assert repository.get("does-not-exist") is None


def test_create_with_explicit_course_and_chat(repository, course_repository, chat_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    chat = chat_repository.create_chat("chat-1", "Physics chat")

    memory = repository.create("mem-1", course.id, chat.id, "Vectors", MemoryKind.NEEDS_REVIEW, "Mixes x/y.")

    assert memory.course_id == course.id
    assert memory.source_chat_id == chat.id


# --- list / filters --------------------------------------------------------------------


def test_list_with_no_filters_returns_everything(repository):
    make(repository, "mem-1", topic="A")
    make(repository, "mem-2", topic="B")

    assert {m.id for m in repository.list()} == {"mem-1", "mem-2"}


def test_list_filters_by_course_id(repository, course_repository):
    physics = course_repository.create_course("physics", "Physics", None, None, None)
    calculus = course_repository.create_course("calc", "Calculus", None, None, None)
    make(repository, "mem-physics", course_id=physics.id)
    make(repository, "mem-calc", course_id=calculus.id)
    make(repository, "mem-global", course_id=None)

    assert [m.id for m in repository.list(course_id=physics.id)] == ["mem-physics"]
    assert [m.id for m in repository.list(course_id=calculus.id)] == ["mem-calc"]


def test_list_course_id_none_means_global_only(repository, course_repository):
    physics = course_repository.create_course("physics", "Physics", None, None, None)
    make(repository, "mem-physics", course_id=physics.id)
    make(repository, "mem-global", course_id=None)

    assert [m.id for m in repository.list(course_id=None)] == ["mem-global"]


def test_list_course_id_unset_means_no_course_filter(repository, course_repository):
    physics = course_repository.create_course("physics", "Physics", None, None, None)
    make(repository, "mem-physics", course_id=physics.id)
    make(repository, "mem-global", course_id=None)

    assert repository.list(course_id=UNSET) == repository.list()


def test_list_filters_by_kind(repository):
    make(repository, "mem-1", topic="A", kind=MemoryKind.NEEDS_REVIEW)
    make(repository, "mem-2", topic="B", kind=MemoryKind.UNDERSTANDS)

    assert [m.id for m in repository.list(kind=MemoryKind.UNDERSTANDS)] == ["mem-2"]


def test_list_filters_by_status(repository):
    make(repository, "mem-1", topic="A")
    make(repository, "mem-2", topic="B")
    repository.archive("mem-2")

    assert [m.id for m in repository.list(status=MemoryStatus.ACTIVE)] == ["mem-1"]
    assert [m.id for m in repository.list(status=MemoryStatus.ARCHIVED)] == ["mem-2"]


def test_list_combines_filters(repository, course_repository):
    physics = course_repository.create_course("physics", "Physics", None, None, None)
    make(repository, "mem-1", course_id=physics.id, kind=MemoryKind.NEEDS_REVIEW)
    make(repository, "mem-2", course_id=physics.id, kind=MemoryKind.UNDERSTANDS)
    repository.archive("mem-2")

    result = repository.list(course_id=physics.id, kind=MemoryKind.UNDERSTANDS, status=MemoryStatus.ARCHIVED)
    assert [m.id for m in result] == ["mem-2"]


def test_list_orders_most_recently_updated_first(repository):
    make(repository, "mem-1", topic="A")
    make(repository, "mem-2", topic="B")
    repository.update("mem-1", topic="A updated")

    assert [m.id for m in repository.list()] == ["mem-1", "mem-2"]


# --- update ------------------------------------------------------------------------------


def test_update_topic_only(repository):
    make(repository)

    updated = repository.update("mem-1", topic="Vector components")

    assert updated.topic == "Vector components"
    assert updated.kind is MemoryKind.NEEDS_REVIEW  # unchanged
    assert updated.summary == "Mixes x/y."  # unchanged


def test_update_kind_only(repository):
    make(repository)

    updated = repository.update("mem-1", kind=MemoryKind.UNDERSTANDS)

    assert updated.kind is MemoryKind.UNDERSTANDS
    assert updated.topic == "Vectors"  # unchanged


def test_update_summary_only(repository):
    make(repository)

    updated = repository.update("mem-1", summary="Now separates components correctly.")

    assert updated.summary == "Now separates components correctly."


def test_update_course_id_to_a_real_course(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    make(repository, course_id=None)

    updated = repository.update("mem-1", course_id=course.id)

    assert updated.course_id == course.id


def test_update_course_id_to_none_unassigns(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    make(repository, course_id=course.id)

    updated = repository.update("mem-1", course_id=None)

    assert updated.course_id is None


def test_update_with_no_course_id_arg_leaves_it_unchanged(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    make(repository, course_id=course.id)

    updated = repository.update("mem-1", topic="New topic")

    assert updated.course_id == course.id


def test_update_bumps_updated_at(repository):
    original = make(repository)

    updated = repository.update("mem-1", topic="New")

    assert updated.updated_at >= original.updated_at


# --- archive / restore ---------------------------------------------------------------


def test_archive_sets_status(repository):
    make(repository)

    archived = repository.archive("mem-1")

    assert archived.status is MemoryStatus.ARCHIVED


def test_restore_sets_status_back_to_active(repository):
    make(repository)
    repository.archive("mem-1")

    restored = repository.restore("mem-1")

    assert restored.status is MemoryStatus.ACTIVE


def test_archive_preserves_all_other_fields(repository):
    make(repository, topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="Mixes x/y.")

    archived = repository.archive("mem-1")

    assert archived.topic == "Vectors"
    assert archived.kind is MemoryKind.NEEDS_REVIEW
    assert archived.summary == "Mixes x/y."


# --- delete ------------------------------------------------------------------------------


def test_delete_removes_the_row(repository):
    make(repository)

    repository.delete("mem-1")

    assert repository.get("mem-1") is None


def test_delete_is_a_hard_delete_not_archive(repository):
    """Distinct from archive: deleted rows disappear from every list,
    including an unfiltered one."""
    make(repository)

    repository.delete("mem-1")

    assert repository.list() == []


# --- Unicode / Burmese / multiline ------------------------------------------------------


def test_unicode_and_burmese_topic_and_summary_round_trip(repository):
    topic = "အရှိန်နှင့် velocity"
    summary = "student confuses acceleration (အရှိန်) with velocity"

    repository.create("mem-1", None, None, topic, MemoryKind.MISCONCEPTION, summary)

    fetched = repository.get("mem-1")
    assert fetched.topic == topic
    assert fetched.summary == summary


def test_cjk_topic_round_trips(repository):
    repository.create("mem-1", None, None, "二次函数", MemoryKind.UNDERSTANDS, "understands quadratics")

    assert repository.get("mem-1").topic == "二次函数"


def test_emoji_in_topic_round_trips(repository):
    repository.create("mem-1", None, None, "Newton's Laws ⚙️", MemoryKind.LEARNING_GOAL, "wants to master this")

    assert repository.get("mem-1").topic == "Newton's Laws ⚙️"


def test_multiline_summary_round_trips(repository):
    summary = "Line one.\nLine two.\n\nLine four after a blank line."

    repository.create("mem-1", None, None, "Topic", MemoryKind.USEFUL_STRATEGY, summary)

    assert repository.get("mem-1").summary == summary


# --- unknown stored kind/status fallback (defensive) -------------------------------------


def test_unknown_stored_kind_falls_back_to_learning_goal(connection, repository):
    connection.execute(
        "INSERT INTO learning_memories (id, topic, kind, summary, status, created_at, updated_at) "
        "VALUES ('mem-x', 'T', 'nonexistent_kind', 'S', 'active', 't', 't')"
    )
    connection.commit()

    memory = repository.get("mem-x")
    assert memory.kind is MemoryKind.LEARNING_GOAL


def test_unknown_stored_status_falls_back_to_active(connection, repository):
    connection.execute(
        "INSERT INTO learning_memories (id, topic, kind, summary, status, created_at, updated_at) "
        "VALUES ('mem-x', 'T', 'understands', 'S', 'nonexistent_status', 't', 't')"
    )
    connection.commit()

    memory = repository.get("mem-x")
    assert memory.status is MemoryStatus.ACTIVE

# Course-deletion archiving lives in SQLiteCourseRepository.
# delete_course_archiving_memories (one transaction spanning the archive and the
# delete); see tests/test_sqlite_course_repository.py for its coverage.
