import pytest

from studybot.core.exceptions import MemoryConflictError, MemoryNotFoundError, SessionError
from studybot.core.learning_memory import MemoryKind, MemoryStatus
from studybot.core.memory_service import MAX_CONTEXT_CHARS, MAX_CONTEXT_ENTRIES, LearningMemoryService
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
def chat_repository(connection):
    return SQLiteChatRepository(connection)


@pytest.fixture
def course_repository(connection):
    return SQLiteCourseRepository(connection)


@pytest.fixture
def memory_repository(connection):
    return SQLiteLearningMemoryRepository(connection)


@pytest.fixture
def service(memory_repository, course_repository, chat_repository):
    return LearningMemoryService(
        repository=memory_repository, course_repository=course_repository, chat_repository=chat_repository
    )


# --- validation --------------------------------------------------------------------------


def test_create_trims_topic(service):
    memory = service.create(topic="  Vectors  ", kind=MemoryKind.NEEDS_REVIEW, summary="s")
    assert memory.topic == "Vectors"


def test_create_collapses_internal_whitespace_in_topic(service):
    memory = service.create(topic="Vector   components", kind=MemoryKind.NEEDS_REVIEW, summary="s")
    assert memory.topic == "Vector components"


def test_create_rejects_empty_topic(service):
    with pytest.raises(SessionError):
        service.create(topic="   ", kind=MemoryKind.NEEDS_REVIEW, summary="s")


def test_create_rejects_topic_over_max_length(service):
    with pytest.raises(SessionError):
        service.create(topic="x" * 201, kind=MemoryKind.NEEDS_REVIEW, summary="s")


def test_create_strips_but_preserves_multiline_summary(service):
    memory = service.create(topic="T", kind=MemoryKind.NEEDS_REVIEW, summary="  Line one.\nLine two.  ")
    assert memory.summary == "Line one.\nLine two."


def test_create_rejects_empty_summary(service):
    with pytest.raises(SessionError):
        service.create(topic="T", kind=MemoryKind.NEEDS_REVIEW, summary="   ")


def test_create_rejects_summary_over_max_length(service):
    with pytest.raises(SessionError):
        service.create(topic="T", kind=MemoryKind.NEEDS_REVIEW, summary="x" * 4001)


def test_create_supports_unicode_burmese_cjk_and_emoji(service):
    memory = service.create(
        topic="Newton's Laws ⚙️",
        kind=MemoryKind.LEARNING_GOAL,
        summary="student wants to master 二次函数 and အရှိန်",
    )
    assert memory.topic == "Newton's Laws ⚙️"
    assert "二次函数" in memory.summary
    assert "အရှိန်" in memory.summary


def test_create_rejects_unknown_course(service):
    with pytest.raises(SessionError):
        service.create(topic="T", kind=MemoryKind.NEEDS_REVIEW, summary="s", course_id="does-not-exist")


def test_create_rejects_unknown_source_chat(service):
    with pytest.raises(SessionError):
        service.create(topic="T", kind=MemoryKind.NEEDS_REVIEW, summary="s", source_chat_id="does-not-exist")


def test_create_with_valid_course_and_chat(service, course_repository, chat_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    chat = chat_repository.create_chat("chat-1", "Physics chat")

    memory = service.create(
        topic="T", kind=MemoryKind.NEEDS_REVIEW, summary="s", course_id=course.id, source_chat_id=chat.id
    )

    assert memory.course_id == course.id
    assert memory.source_chat_id == chat.id


# --- get / list / update / archive / restore / delete: not-found ------------------------


def test_get_raises_memory_not_found(service):
    with pytest.raises(MemoryNotFoundError):
        service.get("does-not-exist")


def test_update_raises_memory_not_found(service):
    with pytest.raises(MemoryNotFoundError):
        service.update("does-not-exist", topic="X")


def test_archive_raises_memory_not_found(service):
    with pytest.raises(MemoryNotFoundError):
        service.archive("does-not-exist")


def test_restore_raises_memory_not_found(service):
    with pytest.raises(MemoryNotFoundError):
        service.restore("does-not-exist")


def test_delete_raises_memory_not_found(service):
    with pytest.raises(MemoryNotFoundError):
        service.delete("does-not-exist")


def test_delete_actually_removes_it(service):
    memory = service.create(topic="T", kind=MemoryKind.NEEDS_REVIEW, summary="s")

    service.delete(memory.id)

    with pytest.raises(MemoryNotFoundError):
        service.get(memory.id)


# --- duplicate policy (Stage 6 §16) -------------------------------------------------------


def test_creating_exact_duplicate_topic_and_kind_raises_conflict(service):
    service.create(topic="Vector components", kind=MemoryKind.NEEDS_REVIEW, summary="s1")

    with pytest.raises(MemoryConflictError):
        service.create(topic="Vector components", kind=MemoryKind.NEEDS_REVIEW, summary="s2")


def test_duplicate_check_is_normalized_case_and_whitespace_insensitive(service):
    service.create(topic="Vector Components", kind=MemoryKind.NEEDS_REVIEW, summary="s1")

    with pytest.raises(MemoryConflictError):
        service.create(topic="  vector   components ", kind=MemoryKind.NEEDS_REVIEW, summary="s2")


def test_duplicate_check_is_scoped_per_course(service, course_repository):
    physics = course_repository.create_course("physics", "Physics", None, None, None)
    calculus = course_repository.create_course("calc", "Calculus", None, None, None)
    service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s1", course_id=physics.id)

    # Same normalized topic+kind, but a different course: no conflict.
    memory = service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s2", course_id=calculus.id)
    assert memory.course_id == calculus.id


def test_duplicate_check_does_not_trigger_across_global_and_course_scope(service, course_repository):
    physics = course_repository.create_course("physics", "Physics", None, None, None)
    service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s1", course_id=physics.id)

    # Same topic+kind but global (course_id=None): different scope, no conflict.
    memory = service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s2", course_id=None)
    assert memory.course_id is None


def test_different_kind_same_topic_is_not_a_duplicate_when_non_opposing(service):
    service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s1")

    # learning_goal never opposes needs_review -> no conflict, no supersession.
    goal = service.create(topic="Vectors", kind=MemoryKind.LEARNING_GOAL, summary="s2")
    assert goal.status is MemoryStatus.ACTIVE

    active = service.list(kind=MemoryKind.NEEDS_REVIEW, status=MemoryStatus.ACTIVE)
    assert len(active) == 1  # the original needs_review memory was not archived


def test_archived_duplicate_does_not_conflict_with_a_new_active_one(service):
    first = service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s1")
    service.archive(first.id)

    # The only existing memory is archived, so this is not a conflict.
    second = service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s2")
    assert second.status is MemoryStatus.ACTIVE


def test_update_into_a_duplicate_raises_conflict(service):
    service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s1")
    other = service.create(topic="Displacement", kind=MemoryKind.NEEDS_REVIEW, summary="s2")

    with pytest.raises(MemoryConflictError):
        service.update(other.id, topic="Vectors")


def test_update_that_does_not_change_topic_or_kind_never_conflicts_with_itself(service):
    memory = service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s1")

    updated = service.update(memory.id, summary="new summary")
    assert updated.summary == "new summary"


def test_restore_into_a_duplicate_raises_conflict(service):
    memory = service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s1")
    service.archive(memory.id)
    service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s2")  # now the active one

    with pytest.raises(MemoryConflictError):
        service.restore(memory.id)


# --- conflicting/superseding memory (Stage 6 §17) -----------------------------------------


def test_creating_understands_archives_existing_active_needs_review_same_topic(service):
    needs_review = service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="struggles")

    understands = service.create(topic="Vectors", kind=MemoryKind.UNDERSTANDS, summary="got it now")

    assert understands.status is MemoryStatus.ACTIVE
    assert service.get(needs_review.id).status is MemoryStatus.ARCHIVED


def test_creating_understands_archives_existing_active_misconception_same_topic(service):
    misconception = service.create(topic="Vectors", kind=MemoryKind.MISCONCEPTION, summary="thinks x=y always")

    service.create(topic="Vectors", kind=MemoryKind.UNDERSTANDS, summary="corrected now")

    assert service.get(misconception.id).status is MemoryStatus.ARCHIVED


def test_supersession_is_symmetric(service):
    understands = service.create(topic="Torque", kind=MemoryKind.UNDERSTANDS, summary="got it")

    service.create(topic="Torque", kind=MemoryKind.NEEDS_REVIEW, summary="struggling again")

    assert service.get(understands.id).status is MemoryStatus.ARCHIVED


def test_supersession_preserves_history_via_archive_not_delete(service):
    needs_review = service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="struggles")

    service.create(topic="Vectors", kind=MemoryKind.UNDERSTANDS, summary="got it now")

    # Still retrievable, not hard-deleted.
    assert service.get(needs_review.id) is not None


def test_supersession_is_scoped_per_course(service, course_repository):
    physics = course_repository.create_course("physics", "Physics", None, None, None)
    calculus = course_repository.create_course("calc", "Calculus", None, None, None)
    physics_needs_review = service.create(
        topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s", course_id=physics.id
    )

    # An "understands" for Calculus must never touch the Physics memory.
    service.create(topic="Vectors", kind=MemoryKind.UNDERSTANDS, summary="s2", course_id=calculus.id)

    assert service.get(physics_needs_review.id).status is MemoryStatus.ACTIVE


def test_update_kind_to_opposing_state_supersedes_the_other_entry(service):
    needs_review = service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s1")
    other = service.create(topic="Displacement", kind=MemoryKind.NEEDS_REVIEW, summary="s2")

    # Change "other"'s topic+kind to collide (opposing) with needs_review's topic.
    service.update(other.id, topic="Vectors", kind=MemoryKind.UNDERSTANDS)

    assert service.get(needs_review.id).status is MemoryStatus.ARCHIVED


def test_restore_that_supersedes_archives_the_other_active_entry(service):
    old_understands = service.create(topic="Vectors", kind=MemoryKind.UNDERSTANDS, summary="old")
    service.archive(old_understands.id)
    needs_review = service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="now struggling")

    service.restore(old_understands.id)

    assert service.get(old_understands.id).status is MemoryStatus.ACTIVE
    assert service.get(needs_review.id).status is MemoryStatus.ARCHIVED


# --- context building (Stage 6 §13-14) -----------------------------------------------------


def test_no_active_memories_returns_none_context(service):
    assert service.build_memory_context_text(None) is None
    assert service.build_memory_context_text("does-not-matter") is None


def test_context_includes_active_course_memories(service, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service.create(
        topic="Vector components", kind=MemoryKind.NEEDS_REVIEW,
        summary="often mixes x/y components", course_id=course.id,
    )

    text = service.build_memory_context_text(course.id)
    assert text is not None
    assert "Vector components" in text
    assert "Needs review" in text
    assert "often mixes x/y components" in text


def test_context_never_includes_raw_kind_identifiers(service, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s", course_id=course.id)

    text = service.build_memory_context_text(course.id)
    assert "needs_review" not in text


def test_context_excludes_archived_memories(service, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    memory = service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s", course_id=course.id)
    service.archive(memory.id)

    assert service.build_memory_context_text(course.id) is None


def test_physics_memories_never_appear_in_calculus_context(service, course_repository):
    physics = course_repository.create_course("physics", "Physics", None, None, None)
    calculus = course_repository.create_course("calc", "Calculus", None, None, None)
    service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="physics stuff", course_id=physics.id)

    calc_text = service.build_memory_context_text(calculus.id)
    assert calc_text is None  # nothing for Calculus at all

    physics_text = service.build_memory_context_text(physics.id)
    assert "Vectors" in physics_text


def test_global_memories_appear_in_every_course_context(service, course_repository):
    physics = course_repository.create_course("physics", "Physics", None, None, None)
    service.create(topic="Study habits", kind=MemoryKind.USEFUL_STRATEGY, summary="works best with worked examples")

    text = service.build_memory_context_text(physics.id)
    assert text is not None
    assert "Study habits" in text


def test_global_memories_appear_in_general_chat_context(service):
    service.create(topic="Study habits", kind=MemoryKind.USEFUL_STRATEGY, summary="works best with worked examples")

    text = service.build_memory_context_text(None)
    assert text is not None
    assert "Study habits" in text


def test_course_specific_memories_never_leak_into_general_chat_context(service, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s", course_id=course.id)

    assert service.build_memory_context_text(None) is None


def test_context_respects_max_entry_count(service, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    for i in range(MAX_CONTEXT_ENTRIES + 8):
        service.create(topic=f"Topic {i}", kind=MemoryKind.LEARNING_GOAL, summary="s", course_id=course.id)

    memories = service.get_active_context_memories(course.id)
    assert len(memories) == MAX_CONTEXT_ENTRIES


def test_context_text_respects_character_budget(service, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    for i in range(MAX_CONTEXT_ENTRIES):
        service.create(
            topic=f"Topic {i}", kind=MemoryKind.LEARNING_GOAL, summary="x" * 300, course_id=course.id
        )

    text = service.build_memory_context_text(course.id)
    assert len(text) <= MAX_CONTEXT_CHARS + 500  # header + at least one entry always included


def test_context_composition_is_deterministic(service, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s", course_id=course.id)

    first = service.build_memory_context_text(course.id)
    second = service.build_memory_context_text(course.id)
    assert first == second


def test_changing_teaching_mode_does_not_alter_stored_memory(service, course_repository):
    """Sanity check at the service layer: nothing here reads or writes
    teaching mode at all — memory context is entirely independent of it."""
    course = course_repository.create_course("c1", "Physics", None, None, None)
    memory = service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s", course_id=course.id)

    # No teaching-mode concept exists in this service; re-fetching confirms
    # the memory is untouched by anything outside explicit memory calls.
    assert service.get(memory.id).topic == "Vectors"


# --- source-chat provenance survives chat deletion ----------------------------------------


def test_memory_survives_source_chat_deletion_with_provenance_cleared(service, chat_repository):
    chat = chat_repository.create_chat("chat-1", "Physics chat")
    memory = service.create(topic="Vectors", kind=MemoryKind.NEEDS_REVIEW, summary="s", source_chat_id=chat.id)

    chat_repository.delete_chat(chat.id)

    survived = service.get(memory.id)
    assert survived is not None
    assert survived.source_chat_id is None
