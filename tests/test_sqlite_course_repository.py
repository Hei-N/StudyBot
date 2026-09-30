import sqlite3

import pytest

from studybot.core.learning_memory import MemoryKind, MemoryStatus
from studybot.storage.database import open_database
from studybot.storage.sqlite_course_repository import SQLiteCourseRepository
from studybot.storage.sqlite_learning_memory_repository import SQLiteLearningMemoryRepository


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "studybot-test.db"


@pytest.fixture
def connection(db_path):
    conn = open_database(db_path)
    yield conn
    conn.close()


@pytest.fixture
def repo(connection):
    return SQLiteCourseRepository(connection)


@pytest.fixture
def memory_repo(connection):
    return SQLiteLearningMemoryRepository(connection)


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


# =====================================================================================
# Stage 6.2 — delete_course_archiving_memories: true transaction-level atomicity
# =====================================================================================


def test_archives_active_memories_and_deletes_the_course(repo, memory_repo):
    course = repo.create_course("c1", "Physics", None, None, None)
    memory = memory_repo.create("m1", course.id, None, "Vectors", MemoryKind.NEEDS_REVIEW, "Mixes x/y.")

    repo.delete_course_archiving_memories(course.id)

    assert repo.get_course(course.id) is None
    survived = memory_repo.get(memory.id)
    assert survived.status is MemoryStatus.ARCHIVED
    assert survived.course_id is None
    assert survived.topic == "Vectors"  # content untouched


def test_never_touches_a_different_courses_memories(repo, memory_repo):
    physics = repo.create_course("physics", "Physics", None, None, None)
    calculus = repo.create_course("calc", "Calculus", None, None, None)
    calc_memory = memory_repo.create("m-calc", calculus.id, None, "Derivatives", MemoryKind.NEEDS_REVIEW, "s")

    repo.delete_course_archiving_memories(physics.id)

    untouched = memory_repo.get(calc_memory.id)
    assert untouched.status is MemoryStatus.ACTIVE
    assert untouched.course_id == calculus.id


def test_never_touches_already_global_memories(repo, memory_repo):
    course = repo.create_course("c1", "Physics", None, None, None)
    global_memory = memory_repo.create("m-global", None, None, "Study habits", MemoryKind.USEFUL_STRATEGY, "s")

    repo.delete_course_archiving_memories(course.id)

    assert memory_repo.get(global_memory.id).status is MemoryStatus.ACTIVE


def test_already_archived_memory_in_the_course_is_left_as_is(repo, memory_repo):
    course = repo.create_course("c1", "Physics", None, None, None)
    memory = memory_repo.create("m1", course.id, None, "Topic", MemoryKind.LEARNING_GOAL, "s")
    memory_repo.archive(memory.id)
    before = memory_repo.get(memory.id).updated_at

    repo.delete_course_archiving_memories(course.id)

    after = memory_repo.get(memory.id)
    assert after.status is MemoryStatus.ARCHIVED
    assert after.updated_at == before  # not re-touched — the UPDATE only matches status='active' rows


def test_course_with_no_memories_deletes_cleanly(repo):
    course = repo.create_course("c1", "Empty", None, None, None)

    repo.delete_course_archiving_memories(course.id)  # must not raise

    assert repo.get_course(course.id) is None


# --- true atomicity: rollback on failure, safe retry ------------------------------------
#
# Sabotage is done with a real SQLite trigger (`RAISE(ABORT, ...)`) that
# fires on the specific course row being deleted, rather than mocking
# `connection.execute` — `sqlite3.Connection` is a C extension type whose
# `execute` attribute can't be monkeypatched (`AttributeError:
# 'sqlite3.Connection' object attribute 'execute' is read-only`), and a real
# trigger is a more faithful stand-in for "the second statement fails for
# some real reason" than mocking would be anyway. Empirically confirmed:
# `RAISE(ABORT, ...)` inside the trigger raises `sqlite3.IntegrityError`,
# and — because it propagates out of the `with self._conn:` block —
# Python's `sqlite3` module rolls back the *entire* transaction (including
# the `UPDATE` that already ran), not just the aborted statement.


def _sabotage_delete_of(connection, course_id: str) -> None:
    connection.execute(
        "CREATE TEMP TRIGGER sabotage_course_delete BEFORE DELETE ON courses "
        f"WHEN OLD.id = '{course_id}' BEGIN SELECT RAISE(ABORT, 'simulated failure'); END"
    )


def _remove_sabotage(connection) -> None:
    connection.execute("DROP TRIGGER IF EXISTS sabotage_course_delete")


def test_rolls_back_the_archive_if_the_course_delete_fails(connection, repo, memory_repo):
    """Sabotage the second statement (the `DELETE FROM courses`) so it
    fails, and verify the first statement (archiving) is rolled back too
    — proving the two statements share one real transaction, not just
    happen to run one after the other."""
    course = repo.create_course("c1", "Physics", None, None, None)
    memory = memory_repo.create("m1", course.id, None, "Vectors", MemoryKind.NEEDS_REVIEW, "s")
    _sabotage_delete_of(connection, course.id)

    with pytest.raises(sqlite3.IntegrityError):
        repo.delete_course_archiving_memories(course.id)

    # Nothing committed: the course is still there, and the memory the
    # sabotaged call *did* manage to UPDATE first was rolled back with it.
    assert repo.get_course(course.id) is not None
    assert memory_repo.get(memory.id).status is MemoryStatus.ACTIVE


def test_safe_to_retry_after_a_rolled_back_failure(connection, repo, memory_repo):
    course = repo.create_course("c1", "Physics", None, None, None)
    memory = memory_repo.create("m1", course.id, None, "Vectors", MemoryKind.NEEDS_REVIEW, "s")
    _sabotage_delete_of(connection, course.id)

    with pytest.raises(sqlite3.IntegrityError):
        repo.delete_course_archiving_memories(course.id)

    # Confirm the rollback left a clean, retryable state...
    assert repo.get_course(course.id) is not None
    assert memory_repo.get(memory.id).status is MemoryStatus.ACTIVE

    # ...and the retry (sabotage removed, as a real fix/retry would follow) succeeds normally.
    _remove_sabotage(connection)
    repo.delete_course_archiving_memories(course.id)

    assert repo.get_course(course.id) is None
    assert memory_repo.get(memory.id).status is MemoryStatus.ARCHIVED


def test_partial_failure_does_not_corrupt_unrelated_memories(connection, repo, memory_repo):
    """The rollback undoes the *whole* transaction, not just the row for
    the course being deleted — a global memory (never touched by the
    UPDATE's WHERE clause in the first place) is naturally unaffected
    either way, but this confirms the sabotage path doesn't do anything
    broader than the real one would."""
    course = repo.create_course("c1", "Physics", None, None, None)
    memory_repo.create("m1", course.id, None, "Vectors", MemoryKind.NEEDS_REVIEW, "s")
    global_memory = memory_repo.create("m-global", None, None, "Study habits", MemoryKind.USEFUL_STRATEGY, "s")
    _sabotage_delete_of(connection, course.id)

    with pytest.raises(sqlite3.IntegrityError):
        repo.delete_course_archiving_memories(course.id)

    assert memory_repo.get(global_memory.id).status is MemoryStatus.ACTIVE


# --- two independent connections to the same database file -----------------------------


def test_visible_atomically_to_a_second_independent_connection(db_path, repo, memory_repo):
    """A second `sqlite3.Connection` to the *same file* (simulating, e.g.,
    the CLI and the API engine each holding their own connection, or a
    process restart) must never see an in-between state: before the call
    it sees the original data, and as soon as the call returns (commits),
    it sees the fully-updated data — never course-gone-but-memory-active
    or memory-archived-but-course-still-there.
    """
    course = repo.create_course("c1", "Physics", None, None, None)
    memory = memory_repo.create("m1", course.id, None, "Vectors", MemoryKind.NEEDS_REVIEW, "s")

    other_connection = open_database(db_path)
    try:
        other_courses = SQLiteCourseRepository(other_connection)
        other_memories = SQLiteLearningMemoryRepository(other_connection)

        # Before: the independent connection already sees the committed rows.
        assert other_courses.get_course(course.id) is not None
        assert other_memories.get(memory.id).status is MemoryStatus.ACTIVE

        repo.delete_course_archiving_memories(course.id)

        # After: the independent connection's next read reflects the full,
        # committed transaction — both changes together, never just one.
        assert other_courses.get_course(course.id) is None
        assert other_memories.get(memory.id).status is MemoryStatus.ARCHIVED
    finally:
        other_connection.close()


def test_second_connections_uncommitted_read_does_not_block_first_connections_write(db_path, repo, memory_repo):
    """A plain read on a second connection (no explicit transaction of its
    own) must not prevent the first connection's atomic operation from
    committing — readers and the one writer here don't deadlock each
    other under SQLite's default rollback-journal mode."""
    course = repo.create_course("c1", "Physics", None, None, None)
    memory_repo.create("m1", course.id, None, "Vectors", MemoryKind.NEEDS_REVIEW, "s")

    other_connection = open_database(db_path)
    try:
        other_courses = SQLiteCourseRepository(other_connection)
        other_courses.get_course(course.id)  # a read, deliberately not wrapped in anything

        repo.delete_course_archiving_memories(course.id)  # must not hang or raise "database is locked"

        assert other_courses.get_course(course.id) is None
    finally:
        other_connection.close()
