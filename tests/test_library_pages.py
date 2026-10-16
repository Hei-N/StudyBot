import hashlib
import sqlite3

import pytest

from studybot.core.exceptions import LibraryFileNotFoundError, LibraryStateError, SessionError
from studybot.core.library import LibraryFileState as S
from studybot.core.library import LibrarySourceKind
from studybot.core.library_service import LibraryService
from studybot.storage.database import SCHEMA_VERSION, get_schema_version, open_database
from studybot.storage.sqlite_course_repository import SQLiteCourseRepository
from studybot.storage.sqlite_library_repository import SQLiteLibraryRepository

H1 = hashlib.sha256(b"one").hexdigest()
H2 = hashlib.sha256(b"two").hexdigest()
V1, V2 = "pdf_text_v1", "pdf_text_v2"
GRANT = ("macos", "security_scoped_bookmark", b"bm")


@pytest.fixture
def connection(tmp_path):
    conn = open_database(tmp_path / "studybot-test.db")
    yield conn
    conn.close()


@pytest.fixture
def repo(connection):
    return SQLiteLibraryRepository(connection)


@pytest.fixture
def library(repo, connection):
    return LibraryService(repo, SQLiteCourseRepository(connection))


@pytest.fixture
def source(library):
    return library.authorize_local_folder("PHY215", "/lib/PHY215", *GRANT)[0]


def prepare(library, source, digest=H1, version=V1, path="a.pdf"):
    return library.prepare_pdf_import(
        source.id, path, display_name=None, size_bytes=10, content_hash=digest, processing_version=version
    )


def import_pages(library, source, pages, digest=H1, version=V1, path="a.pdf"):
    plan = prepare(library, source, digest, version, path)
    assert plan.needs_extraction
    return library.complete_pdf_import(
        plan.file.id, digest, pages=[(i + 1, t) for i, t in enumerate(pages)], processing_version=version
    )


# --- schema --------------------------------------------------------------------------


def test_fresh_v8_database_has_pages_and_extraction_columns(connection):
    assert get_schema_version(connection) == SCHEMA_VERSION == 8
    columns = {r["name"] for r in connection.execute("PRAGMA table_info(library_files)")}
    assert {"page_count", "text_page_count", "processing_version"} <= columns
    page_columns = {r["name"]: r for r in connection.execute("PRAGMA table_info(library_pages)")}
    assert set(page_columns) == {"file_id", "page_number", "text_content", "char_count", "created_at", "updated_at"}
    assert page_columns["file_id"]["pk"] == 1 and page_columns["page_number"]["pk"] == 2
    [fk] = list(connection.execute("PRAGMA foreign_key_list(library_pages)"))
    assert (fk["from"], fk["table"], fk["on_delete"]) == ("file_id", "library_files", "CASCADE")


def test_page_constraints(connection, library, source):
    file = library.register_or_update_file(source.id, "a.pdf")
    insert = "INSERT INTO library_pages VALUES (?, ?, 'x', ?, 't', 't')"
    for bad in [(file.id, 0, 1), (file.id, 1, -1), ("missing-file", 1, 1)]:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert, bad)
    connection.execute(insert, (file.id, 1, 1))
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(insert, (file.id, 1, 1))  # one row per file + page number


def _seed_old(conn):
    conn.execute("INSERT INTO courses VALUES ('c1', 'Physics', NULL, NULL, NULL, 't', 't')")
    conn.execute("INSERT INTO chats VALUES ('chat1', 'Chat', 'c1', 'homework', 'deep', 't', 't')")
    conn.execute("INSERT INTO messages (chat_id, role, content, created_at) VALUES ('chat1', 'user', 'hi', 't')")
    conn.execute("INSERT INTO learning_memories VALUES ('m1', 'c1', 'chat1', 'T', 'needs_review', 's', 'active', 't', 't')")


def _seed_library(conn, with_authorization):
    conn.execute("INSERT INTO library_sources VALUES ('s1', 'c1', 'local_folder', 'Phys', '/x', 't', 't')")
    conn.execute(
        "INSERT INTO library_files (id, source_id, relative_path, display_name, created_at, updated_at) "
        "VALUES ('f1', 's1', 'a.pdf', 'a', 't', 't')"
    )
    if with_authorization:
        conn.execute("INSERT INTO library_source_authorizations VALUES ('s1', 'macos', 'security_scoped_bookmark', x'01', 't', 't')")


def _build_old_database(path, version):
    from studybot.storage import database

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    statements = list(database._FRESH_SCHEMA_STATEMENTS)
    if version >= 6:
        statements += database._LIBRARY_SCHEMA_STATEMENTS
    if version >= 7:
        statements += database._LIBRARY_AUTHORIZATION_STATEMENTS
    for statement in statements:
        conn.execute(statement)
    _seed_old(conn)
    if version >= 6:
        _seed_library(conn, with_authorization=version >= 7)
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    return conn


@pytest.mark.parametrize("old_version", [7, 6])
def test_old_databases_migrate_to_v8_preserving_everything(tmp_path, old_version):
    db_path = tmp_path / "studybot.db"
    _build_old_database(db_path, old_version).close()

    connection = open_database(db_path)
    try:
        assert get_schema_version(connection) == 8
        assert connection.execute("SELECT summary FROM learning_memories").fetchone()[0] == "s"
        assert connection.execute("SELECT content FROM messages").fetchone()[0] == "hi"
        file = connection.execute("SELECT * FROM library_files").fetchone()
        assert file["relative_path"] == "a.pdf" and file["processing_state"] == "pending"
        assert (file["page_count"], file["text_page_count"], file["processing_version"]) == (None, None, None)
        assert connection.execute("SELECT COUNT(*) FROM library_pages").fetchone()[0] == 0
        if old_version >= 7:
            assert connection.execute("SELECT COUNT(*) FROM library_source_authorizations").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
    again = open_database(db_path)  # exactly once
    assert get_schema_version(again) == 8
    again.close()


def test_v5_database_migrates_to_v8(tmp_path):
    from tests.test_library_schema import _create_v5_database, _seed_v5

    db_path = tmp_path / "studybot.db"
    seed = _create_v5_database(db_path)
    _seed_v5(seed)
    seed.close()

    connection = open_database(db_path)
    try:
        assert get_schema_version(connection) == 8
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"library_sources", "library_files", "library_source_authorizations", "library_pages"} <= tables
        assert connection.execute("SELECT summary FROM learning_memories").fetchone()[0] == "sum"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_failed_v8_migration_leaves_the_v7_database_untouched(tmp_path):
    db_path = tmp_path / "studybot.db"
    _build_old_database(db_path, 7).close()
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE library_pages (bogus INTEGER)")
    conn.commit()
    conn.close()

    with pytest.raises(sqlite3.OperationalError):
        open_database(db_path)

    verify = sqlite3.connect(db_path)
    columns = {r[1] for r in verify.execute("PRAGMA table_info(library_files)")}
    assert verify.execute("PRAGMA user_version").fetchone()[0] == 7
    assert "page_count" not in columns  # the ALTERs rolled back with the failed table creation
    verify.close()


# --- service: import lifecycle -------------------------------------------------------


def test_import_stores_pages_and_metadata_atomically(library, repo, source):
    file = import_pages(library, source, ["page one", "", "page three"])

    assert file.processing_state is S.READY and file.indexed_at
    assert (file.page_count, file.text_page_count, file.processing_version) == (3, 2, V1)
    pages = repo.list_pages(file.id)
    assert [(p.page_number, p.char_count) for p in pages] == [(1, 8), (2, 0), (3, 10)]
    assert pages[1].text_content == ""


def test_prepare_skips_unchanged_ready_content(library, repo, source):
    ready = import_pages(library, source, ["x"])

    plan = prepare(library, source)

    assert not plan.needs_extraction and plan.file.id == ready.id
    assert plan.file.indexed_at == ready.indexed_at and len(repo.list_pages(ready.id)) == 1


def test_prepare_reprocesses_when_the_version_changes(library, repo, source):
    ready = import_pages(library, source, ["x"])

    plan = prepare(library, source, version=V2)

    assert plan.needs_extraction and plan.file.id == ready.id and plan.file.processing_state is S.INDEXING
    assert len(repo.list_pages(ready.id)) == 1  # old pages stay until the new ones replace them


def test_prepare_reprocesses_changed_content_and_keeps_the_id(library, source):
    ready = import_pages(library, source, ["x"])

    plan = prepare(library, source, digest=H2)

    assert plan.needs_extraction and plan.file.id == ready.id and plan.file.content_hash == H2


def test_prepare_retries_a_failed_file(library, source):
    plan = prepare(library, source)
    failed = library.fail_pdf_import(plan.file.id, "invalid_pdf")
    assert failed.processing_state is S.FAILED

    retry = prepare(library, source)

    assert retry.needs_extraction and retry.file.id == failed.id
    assert retry.file.processing_state is S.INDEXING and retry.file.failure_code is None


def test_a_file_already_indexing_is_not_started_twice(library, source):
    prepare(library, source)

    with pytest.raises(LibraryStateError):
        prepare(library, source)


def test_import_requires_an_authorized_source_and_a_pdf_path(library):
    plain = library.create_source(LibrarySourceKind.LOCAL_FOLDER, "Plain", "/lib/plain")

    from studybot.core.exceptions import LibraryAuthorizationNotFoundError

    with pytest.raises(LibraryAuthorizationNotFoundError):
        prepare(library, plain)
    authorized = library.authorize_local_folder("A", "/lib/a", *GRANT)[0]
    with pytest.raises(SessionError):
        prepare(library, authorized, path="notes.txt")


def test_mark_ready_validates_the_result_shape(library, source):
    plan = prepare(library, source)

    with pytest.raises(SessionError):
        library.mark_ready(plan.file.id, H1, page_count=2, text_page_count=3, processing_version=V1)
    with pytest.raises(SessionError):
        library.mark_ready(plan.file.id, H1, page_count=2, text_page_count=1, processing_version="")
    with pytest.raises(SessionError):
        library.mark_ready(plan.file.id, H1, page_count=2, text_page_count=1, processing_version=V1,
                           pages=[(1, "a"), (3, "b")])  # not numbered 1..N
    assert library.get_file(plan.file.id).processing_state is S.INDEXING


def test_content_changing_during_processing_cannot_be_recorded_as_current(library, source):
    plan = prepare(library, source)
    library.register_or_update_file(source.id, "a.pdf", content_hash=H2)  # bytes changed mid-import

    with pytest.raises(LibraryStateError):
        library.complete_pdf_import(plan.file.id, H1, pages=[(1, "x")], processing_version=V1)
    assert library.get_file(plan.file.id).processing_state is S.INDEXING


def test_fail_pdf_import_is_a_no_op_for_missing_or_finished_files(library, source):
    assert library.fail_pdf_import("missing", "x") is None
    ready = import_pages(library, source, ["x"])
    assert library.fail_pdf_import(ready.id, "extraction_failed").processing_state is S.READY


# --- interrupted recovery ------------------------------------------------------------


def test_interrupted_indexing_is_failed_on_startup_and_can_be_retried(tmp_path):
    from studybot.config.settings import Settings
    from studybot.app import StudyBotApp

    settings = Settings.from_env(env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)})
    first = StudyBotApp(settings)
    source = first.library.authorize_local_folder("P", "/lib/p", *GRANT)[0]
    plan = first.library.prepare_pdf_import(
        source.id, "a.pdf", display_name=None, size_bytes=1, content_hash=H1, processing_version=V1
    )
    first.close()  # the process "dies" while the file is indexing

    second = StudyBotApp(settings)
    try:
        file = second.library.get_file(plan.file.id)
        assert file.processing_state is S.FAILED and file.failure_code == "interrupted"
        assert second.library._library.list_pages(file.id) == []  # nothing fabricated
        retry = second.library.prepare_pdf_import(
            source.id, "a.pdf", display_name=None, size_bytes=1, content_hash=H1, processing_version=V1
        )
        assert retry.needs_extraction and retry.file.id == file.id
    finally:
        second.close()


# --- transactions --------------------------------------------------------------------


def _page_rows(connection, file_id):
    return connection.execute(
        "SELECT page_number, text_content FROM library_pages WHERE file_id = ? ORDER BY page_number", (file_id,)
    ).fetchall()


def test_failure_midway_through_page_insertion_keeps_the_old_pages(library, connection, source):
    old = import_pages(library, source, ["old one", "old two"])
    plan = prepare(library, source, digest=H2)
    connection.execute(
        "CREATE TRIGGER fail_page_2 BEFORE INSERT ON library_pages WHEN new.page_number = 2 "
        "BEGIN SELECT RAISE(ABORT, 'blocked'); END"
    )

    with pytest.raises(sqlite3.IntegrityError):
        library.complete_pdf_import(plan.file.id, H2, pages=[(1, "new one"), (2, "new two")], processing_version=V1)

    assert [t for _, t in _page_rows(connection, old.id)] == ["old one", "old two"]
    current = library.get_file(old.id)
    assert current.processing_state is S.INDEXING and current.content_hash == H2  # not ready for the new content


def test_failure_while_marking_ready_does_not_commit_new_pages(library, connection, source):
    old = import_pages(library, source, ["old"])
    plan = prepare(library, source, digest=H2)
    connection.execute(
        "CREATE TRIGGER fail_ready BEFORE UPDATE ON library_files WHEN new.processing_state = 'ready' "
        "BEGIN SELECT RAISE(ABORT, 'blocked'); END"
    )

    with pytest.raises(sqlite3.IntegrityError):
        library.complete_pdf_import(plan.file.id, H2, pages=[(1, "new"), (2, "newer")], processing_version=V1)

    assert [t for _, t in _page_rows(connection, old.id)] == ["old"]
    assert library.get_file(old.id).processing_state is S.INDEXING


def test_source_deleted_before_finalization_leaves_no_orphan_pages(library, connection, source):
    plan = prepare(library, source)
    library.delete_source(source.id)

    with pytest.raises(LibraryFileNotFoundError):
        library.complete_pdf_import(plan.file.id, H1, pages=[(1, "x")], processing_version=V1)

    assert connection.execute("SELECT COUNT(*) FROM library_pages").fetchone()[0] == 0


def test_deleting_a_file_or_source_removes_its_pages(library, repo, connection, source, tmp_path):
    real = tmp_path / "a.pdf"
    real.write_bytes(b"user pdf")
    first = import_pages(library, source, ["x", "y"], path="a.pdf")
    second = import_pages(library, source, ["z"], digest=H2, path="b.pdf")

    library.delete_file(first.id)
    assert repo.list_pages(first.id) == [] and len(repo.list_pages(second.id)) == 1
    library.delete_source(source.id)

    assert connection.execute("SELECT COUNT(*) FROM library_pages").fetchone()[0] == 0
    assert real.read_bytes() == b"user pdf"


def test_course_deletion_keeps_pages(library, repo, connection, source):
    from studybot.core.course_service import CourseService
    from studybot.storage.sqlite_repository import SQLiteChatRepository

    courses = CourseService(SQLiteCourseRepository(connection), SQLiteChatRepository(connection))
    course = courses.create_course("Physics")
    library.assign_source_to_course(source.id, course.id)
    file = import_pages(library, source, ["x"])

    courses.delete_course(course.id)

    assert library.get_source(source.id).course_id is None and len(repo.list_pages(file.id)) == 1
