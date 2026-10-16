import hashlib
import os
import shutil
import sqlite3

import pytest

from studybot.core.course_service import CourseService
from studybot.core.exceptions import (
    CourseNotFoundError,
    LibraryConflictError,
    LibraryFileNotFoundError,
    LibrarySourceNotFoundError,
    LibraryStateError,
    SessionError,
)
from studybot.core.learning_memory import MemoryKind, MemoryStatus
from studybot.core.library import LibraryFileState as S
from studybot.core.library import LibrarySourceKind
from studybot.core.library_service import LibraryService
from studybot.storage.database import open_database
from studybot.storage.sqlite_course_repository import SQLiteCourseRepository
from studybot.storage.sqlite_learning_memory_repository import SQLiteLearningMemoryRepository
from studybot.storage.sqlite_library_repository import SQLiteLibraryRepository
from studybot.storage.sqlite_repository import SQLiteChatRepository

READY = {"page_count": 1, "text_page_count": 1, "processing_version": "pdf_text_v1"}
ABC = hashlib.sha256(b"ABC").hexdigest()
DEF = hashlib.sha256(b"DEF").hexdigest()


@pytest.fixture
def connection(tmp_path):
    conn = open_database(tmp_path / "studybot-test.db")
    yield conn
    conn.close()


@pytest.fixture
def courses(connection):
    return CourseService(SQLiteCourseRepository(connection), SQLiteChatRepository(connection))


@pytest.fixture
def library(connection):
    return LibraryService(SQLiteLibraryRepository(connection), SQLiteCourseRepository(connection))


@pytest.fixture
def source(library, tmp_path):
    return library.create_source(LibrarySourceKind.LOCAL_FOLDER, "Physics", str(tmp_path / "PHY215"))


def ready_file(library, source, path="Week 2/Lecture.pdf", digest=ABC):
    file = library.register_or_update_file(source.id, path, content_hash=digest)
    library.begin_indexing(file.id)
    return library.mark_ready(file.id, digest, **READY)


# --- sources -------------------------------------------------------------------------


def test_create_source_stores_normalized_metadata(library, tmp_path):
    source = library.create_source("local_folder", "  Physics   215 ", f"{tmp_path}//PHY215/")

    assert source.display_name == "Physics 215"
    assert source.locator == f"{tmp_path}/PHY215"
    assert source.kind is LibrarySourceKind.LOCAL_FOLDER
    assert source.course_id is None
    assert source.created_at == source.updated_at
    assert library.get_source(source.id) == source


def test_create_source_does_not_touch_the_filesystem(library, tmp_path):
    missing = tmp_path / "does-not-exist"

    library.create_source(LibrarySourceKind.LOCAL_FOLDER, "Ghost", str(missing))

    assert not missing.exists()


@pytest.mark.parametrize(("kind", "name", "locator"), [("google_drive", "x", "/x"), ("local_file", "", "/x"), ("local_file", "x", " ")])
def test_create_source_validates_input(library, kind, name, locator):
    with pytest.raises(SessionError):
        library.create_source(kind, name, locator)


def test_exact_duplicate_source_is_rejected_but_other_kinds_are_not(library, tmp_path):
    library.create_source(LibrarySourceKind.LOCAL_FOLDER, "A", str(tmp_path / "x"))

    with pytest.raises(LibraryConflictError):
        library.create_source(LibrarySourceKind.LOCAL_FOLDER, "B", f"{tmp_path}/x/")
    other_kind = library.create_source(LibrarySourceKind.LOCAL_FILE, "C", str(tmp_path / "x"))

    assert other_kind.kind is LibrarySourceKind.LOCAL_FILE
    assert len(library.list_sources()) == 2


def test_source_course_association(library, courses, source):
    physics = courses.create_course("Physics")
    maths = courses.create_course("Maths")
    file = library.register_or_update_file(source.id, "a.pdf")

    assigned = library.assign_source_to_course(source.id, physics.id)
    reassigned = library.assign_source_to_course(source.id, maths.id)
    cleared = library.unassign_source_from_course(source.id)

    assert assigned.course_id == physics.id
    assert reassigned.id == source.id and reassigned.course_id == maths.id
    assert cleared.course_id is None
    assert library.get_file(file.id).source_id == source.id


def test_assigning_to_a_missing_course_fails_cleanly(library, source):
    with pytest.raises(CourseNotFoundError):
        library.assign_source_to_course(source.id, "no-such-course")
    with pytest.raises(CourseNotFoundError):
        library.create_source(LibrarySourceKind.LOCAL_FILE, "x", "/x", course_id="no-such-course")
    assert library.get_source(source.id).course_id is None


def test_missing_source_raises_not_found(library):
    for call in (
        lambda: library.assign_source_to_course("nope", "c"),
        lambda: library.unassign_source_from_course("nope"),
        lambda: library.delete_source("nope"),
        lambda: library.register_or_update_file("nope", "a.pdf"),
    ):
        with pytest.raises(LibrarySourceNotFoundError):
            call()


def test_list_sources_can_filter_by_course(library, courses, tmp_path):
    course = courses.create_course("Physics")
    a = library.create_source(LibrarySourceKind.LOCAL_FOLDER, "A", str(tmp_path / "a"), course_id=course.id)
    b = library.create_source(LibrarySourceKind.LOCAL_FOLDER, "B", str(tmp_path / "b"))

    assert {s.id for s in library.list_sources()} == {a.id, b.id}
    assert [s.id for s in library.list_sources(course_id=course.id)] == [a.id]
    assert [s.id for s in library.list_sources(course_id=None)] == [b.id]


# --- course deletion -----------------------------------------------------------------


def test_deleting_a_course_keeps_sources_and_files(library, courses):
    course = courses.create_course("Physics")
    source = library.create_source(LibrarySourceKind.LOCAL_FOLDER, "Phys", "/library/phy", course_id=course.id)
    file = library.register_or_update_file(source.id, "Week 1/a.pdf")

    courses.delete_course(course.id)

    kept = library.get_source(source.id)
    assert kept is not None and kept.course_id is None
    assert library.get_file(file.id) is not None
    assert courses.get_course(course.id) is None


def test_course_deletion_still_archives_learning_memories(connection, library, courses):
    course = courses.create_course("Physics")
    memories = SQLiteLearningMemoryRepository(connection)
    memories.create("m1", course.id, None, "Vectors", MemoryKind.NEEDS_REVIEW, "review", MemoryStatus.ACTIVE)
    library.create_source(LibrarySourceKind.LOCAL_FOLDER, "Phys", "/library/phy", course_id=course.id)

    courses.delete_course(course.id)

    assert memories.get("m1").status is MemoryStatus.ARCHIVED


# --- source and file deletion never touch the disk -----------------------------------


@pytest.fixture
def forbid_filesystem_deletes(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("filesystem deletion attempted")

    for owner, name in [(os, "remove"), (os, "unlink"), (os, "rmdir"), (os, "removedirs"), (shutil, "rmtree")]:
        monkeypatch.setattr(owner, name, refuse)


def test_deleting_a_source_removes_file_metadata_only(library, tmp_path, forbid_filesystem_deletes):
    real = tmp_path / "PHY215"
    real.mkdir()
    (real / "a.pdf").write_bytes(b"keep me")
    source = library.create_source(LibrarySourceKind.LOCAL_FOLDER, "Phys", str(real))
    f1 = library.register_or_update_file(source.id, "a.pdf")
    f2 = library.register_or_update_file(source.id, "b/c.pdf")

    library.delete_source(source.id)

    assert library.get_source(source.id) is None
    assert library.get_file(f1.id) is None and library.get_file(f2.id) is None
    assert (real / "a.pdf").read_bytes() == b"keep me"


def test_deleting_a_file_record_never_deletes_the_real_file(library, source, tmp_path, forbid_filesystem_deletes):
    real = tmp_path / "lecture.pdf"
    real.write_bytes(b"data")
    file = library.register_or_update_file(source.id, "lecture.pdf")

    deleted = library.delete_file(file.id)

    assert deleted.id == file.id and library.get_file(file.id) is None
    assert real.read_bytes() == b"data"
    with pytest.raises(LibraryFileNotFoundError):
        library.delete_file(file.id)


# --- file registration ---------------------------------------------------------------


def test_new_file_is_pending_with_unknown_hash(library, source):
    file = library.register_or_update_file(source.id, "Week 2/Lecture.PDF", size_bytes=10, modified_at="2026-01-01T00:00:00Z")

    assert file.processing_state is S.PENDING
    assert file.content_hash is None and file.indexed_at is None and file.failure_code is None
    assert file.display_name == "Lecture.PDF" and file.extension == "pdf"
    assert (file.size_bytes, file.modified_at) == (10, "2026-01-01T00:00:00Z")


def test_registering_the_same_path_twice_updates_in_place(library, source):
    first = library.register_or_update_file(source.id, "Notes/a.txt", size_bytes=1)
    second = library.register_or_update_file(source.id, "./Notes//a.txt", size_bytes=2, display_name="Renamed")

    assert second.id == first.id
    assert len(library.list_files(source_id=source.id)) == 1
    assert second.size_bytes == 2 and second.display_name == "Renamed"
    assert second.created_at == first.created_at


def test_same_path_under_different_sources_is_allowed(library, source, tmp_path):
    other = library.create_source(LibrarySourceKind.LOCAL_FOLDER, "Other", str(tmp_path / "other"))

    a = library.register_or_update_file(source.id, "a.pdf")
    b = library.register_or_update_file(other.id, "a.pdf")

    assert a.id != b.id


@pytest.mark.parametrize("path", ["../secret.pdf", "../../file.pdf", "/absolute/file.pdf", ""])
def test_register_rejects_unsafe_paths(library, source, path):
    with pytest.raises(SessionError):
        library.register_or_update_file(source.id, path)
    assert library.list_files(source_id=source.id) == []


def test_register_validates_metadata(library, source):
    with pytest.raises(SessionError):
        library.register_or_update_file(source.id, "a.pdf", size_bytes=-1)
    with pytest.raises(SessionError):
        library.register_or_update_file(source.id, "a.pdf", content_hash="not-a-hash")


def test_unchanged_content_keeps_the_file_ready(library, source):
    file = ready_file(library, source)

    updated = library.register_or_update_file(
        source.id, "Week 2/Lecture.pdf", modified_at="2027-05-05T00:00:00Z", size_bytes=99, content_hash=ABC.upper()
    )

    assert updated.id == file.id
    assert updated.processing_state is S.READY
    assert updated.indexed_at == file.indexed_at
    assert updated.modified_at == "2027-05-05T00:00:00Z"


def test_modification_time_alone_does_not_invalidate_ready_content(library, source):
    file = ready_file(library, source)

    updated = library.register_or_update_file(source.id, "Week 2/Lecture.pdf", modified_at="2030-01-01T00:00:00Z")

    assert updated.processing_state is S.READY and updated.content_hash == ABC
    assert updated.indexed_at == file.indexed_at


def test_unknown_hash_never_marks_ready_content_stale(library, source):
    ready_file(library, source)

    updated = library.register_or_update_file(source.id, "Week 2/Lecture.pdf", size_bytes=5)

    assert updated.processing_state is S.READY and updated.content_hash == ABC


def test_changed_content_marks_a_ready_file_stale_in_place(library, source):
    file = ready_file(library, source)

    updated = library.register_or_update_file(source.id, "Week 2/Lecture.pdf", content_hash=DEF)

    assert updated.id == file.id and updated.source_id == source.id
    assert updated.processing_state is S.STALE and updated.content_hash == DEF
    assert library.get_file(file.id) is not None
    assert len(library.list_files(source_id=source.id)) == 1


def test_a_new_hash_does_not_invent_transitions_for_other_states(library, source):
    pending = library.register_or_update_file(source.id, "p.pdf", content_hash=ABC)
    assert library.register_or_update_file(source.id, "p.pdf", content_hash=DEF).processing_state is S.PENDING
    failed = library.register_or_update_file(source.id, "f.pdf", content_hash=ABC)
    library.begin_indexing(failed.id)
    library.mark_failed(failed.id, "read_failed")
    again = library.register_or_update_file(source.id, "f.pdf", content_hash=DEF)
    assert again.processing_state is S.FAILED and again.failure_code == "read_failed"
    assert pending.id != failed.id


def test_no_op_update_does_not_touch_updated_at(library, source):
    file = library.register_or_update_file(source.id, "a.pdf", size_bytes=1)

    same = library.register_or_update_file(source.id, "a.pdf", size_bytes=1)

    assert same.updated_at == file.updated_at


# --- state machine -------------------------------------------------------------------


def test_normal_lifecycle(library, source):
    file = library.register_or_update_file(source.id, "a.pdf", content_hash=ABC)

    indexing = library.begin_indexing(file.id)
    ready = library.mark_ready(file.id, ABC, **READY)

    assert indexing.processing_state is S.INDEXING
    assert ready.processing_state is S.READY and ready.indexed_at is not None and ready.failure_code is None
    assert ready.id == file.id


def test_failure_and_retry_cycle(library, source):
    file = library.register_or_update_file(source.id, "a.pdf", content_hash=ABC)
    library.begin_indexing(file.id)

    failed = library.mark_failed(file.id, "unsupported_type")
    retried = library.retry_file(file.id)

    assert failed.processing_state is S.FAILED and failed.failure_code == "unsupported_type"
    assert failed.content_hash == ABC
    assert retried.processing_state is S.PENDING and retried.failure_code is None
    assert len(library.list_files(source_id=source.id)) == 1


def test_stale_cycle(library, source):
    file = ready_file(library, source)

    stale = library.mark_stale(file.id)
    indexing = library.begin_indexing(file.id)
    ready = library.mark_ready(file.id, ABC, **READY)

    assert stale.processing_state is S.STALE
    assert indexing.processing_state is S.INDEXING
    assert ready.processing_state is S.READY


@pytest.mark.parametrize(
    "attempt",
    [
        lambda lib, f: lib.mark_ready(f, ABC, **READY),  # pending -> ready
        lambda lib, f: lib.mark_failed(f, "read_failed"),  # pending -> failed
        lambda lib, f: lib.mark_stale(f),  # pending -> stale
        lambda lib, f: lib.retry_file(f),  # pending -> pending
    ],
)
def test_invalid_transitions_from_pending(library, source, attempt):
    file = library.register_or_update_file(source.id, "a.pdf", content_hash=ABC)

    with pytest.raises(LibraryStateError):
        attempt(library, file.id)
    assert library.get_file(file.id).processing_state is S.PENDING


def test_ready_cannot_fail_or_restart_directly(library, source):
    file = ready_file(library, source)

    for attempt in (lambda: library.mark_failed(file.id, "x"), lambda: library.begin_indexing(file.id), lambda: library.retry_file(file.id)):
        with pytest.raises(LibraryStateError):
            attempt()
    assert library.get_file(file.id).processing_state is S.READY


def test_failed_cannot_become_ready_or_start_without_retry(library, source):
    file = library.register_or_update_file(source.id, "a.pdf", content_hash=ABC)
    library.begin_indexing(file.id)
    library.mark_failed(file.id, "read_failed")

    with pytest.raises(LibraryStateError):
        library.mark_ready(file.id, ABC, **READY)
    with pytest.raises(LibraryStateError):
        library.begin_indexing(file.id)


def test_ready_requires_a_known_matching_hash(library, source):
    unknown = library.register_or_update_file(source.id, "u.pdf")
    library.begin_indexing(unknown.id)
    with pytest.raises(LibraryStateError):
        library.mark_ready(unknown.id, ABC, **READY)

    file = library.register_or_update_file(source.id, "a.pdf", content_hash=ABC)
    library.begin_indexing(file.id)
    library.register_or_update_file(source.id, "a.pdf", content_hash=DEF)  # content changed while indexing
    with pytest.raises(LibraryStateError):
        library.mark_ready(file.id, ABC, **READY)
    assert library.get_file(file.id).processing_state is S.INDEXING
    assert library.mark_ready(file.id, DEF, **READY).processing_state is S.READY


def test_failure_code_must_be_machine_readable(library, source):
    file = library.register_or_update_file(source.id, "a.pdf", content_hash=ABC)
    library.begin_indexing(file.id)

    with pytest.raises(SessionError):
        library.mark_failed(file.id, "Traceback (most recent call last): boom")
    assert library.get_file(file.id).processing_state is S.INDEXING


def test_state_operations_on_missing_files(library):
    for attempt in (
        lambda: library.begin_indexing("nope"),
        lambda: library.mark_ready("nope", ABC, **READY),
        lambda: library.mark_failed("nope", "x"),
        lambda: library.mark_stale("nope"),
        lambda: library.retry_file("nope"),
    ):
        with pytest.raises(LibraryFileNotFoundError):
            attempt()


def test_list_files_by_source_and_state(library, source, tmp_path):
    other = library.create_source(LibrarySourceKind.LOCAL_FOLDER, "Other", str(tmp_path / "o"))
    a = library.register_or_update_file(source.id, "a.pdf", content_hash=ABC)
    library.register_or_update_file(source.id, "b.pdf")
    library.register_or_update_file(other.id, "c.pdf")
    library.begin_indexing(a.id)

    assert [f.relative_path for f in library.list_files(source_id=source.id)] == ["a.pdf", "b.pdf"]
    assert [f.relative_path for f in library.list_files(state=S.INDEXING)] == ["a.pdf"]
    assert len(library.list_files()) == 3
    assert [f.relative_path for f in library.list_files(source_id=other.id, state=S.PENDING)] == ["c.pdf"]


# --- no stray side effects -----------------------------------------------------------


def test_library_modules_contain_no_filesystem_deletion_or_scanning():
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "src" / "studybot"
    for name in ["core/library.py", "core/library_service.py", "storage/sqlite_library_repository.py"]:
        text = (root / name).read_text()
        for forbidden in ["os.remove", "unlink(", "rmtree", "os.walk", "scandir", "glob(", "iterdir", "listdir", "rmdir"]:
            assert forbidden not in text, (name, forbidden)


def test_sqlite_errors_do_not_leak_for_duplicate_sources(library, connection, tmp_path):
    library.create_source(LibrarySourceKind.LOCAL_FILE, "A", "/x/file.pdf")

    with pytest.raises(LibraryConflictError):
        SQLiteLibraryRepository(connection).create_source("dup", None, LibrarySourceKind.LOCAL_FILE, "B", "/x/file.pdf")
    assert not isinstance(LibraryConflictError("x"), sqlite3.Error)
