import sqlite3

import pytest

from studybot.core.course_service import CourseService
from studybot.core.exceptions import (
    LibraryAuthorizationNotFoundError,
    LibrarySourceNotFoundError,
    SessionError,
)
from studybot.core.library import MAX_AUTHORIZATION_BYTES, LibrarySourceKind
from studybot.core.library_service import LibraryService
from studybot.storage.database import SCHEMA_VERSION, get_schema_version, open_database
from studybot.storage.sqlite_course_repository import SQLiteCourseRepository
from studybot.storage.sqlite_library_repository import SQLiteLibraryRepository
from studybot.storage.sqlite_repository import SQLiteChatRepository

PAYLOAD = b"opaque-bookmark"
GRANT = ("macos", "security_scoped_bookmark", PAYLOAD)


@pytest.fixture
def connection(tmp_path):
    conn = open_database(tmp_path / "studybot-test.db")
    yield conn
    conn.close()


@pytest.fixture
def library(connection):
    return LibraryService(SQLiteLibraryRepository(connection), SQLiteCourseRepository(connection))


@pytest.fixture
def courses(connection):
    return CourseService(SQLiteCourseRepository(connection), SQLiteChatRepository(connection))


# --- service -------------------------------------------------------------------------


def test_authorizing_a_new_folder_creates_source_and_grant_together(library):
    source, created = library.authorize_local_folder("PHY215", "/lib/PHY215/", *GRANT)

    assert created and source.locator == "/lib/PHY215" and source.course_id is None
    assert source.kind is LibrarySourceKind.LOCAL_FOLDER
    assert library.get_authorization(source.id).payload == PAYLOAD
    assert library.authorized_source_ids() == {source.id}


def test_authorizing_a_known_folder_reuses_it_and_keeps_its_files_and_course(library, courses):
    course = courses.create_course("Physics")
    first, _ = library.authorize_local_folder("PHY215", "/lib/PHY215", *GRANT)
    library.assign_source_to_course(first.id, course.id)
    file = library.register_or_update_file(first.id, "a.pdf")

    second, created = library.authorize_local_folder("Renamed", "/lib//PHY215/", "macos", "security_scoped_bookmark", b"fresh")

    assert not created and second.id == first.id
    assert library.get_source(first.id).course_id == course.id
    assert library.get_source(first.id).display_name == "PHY215"
    assert library.get_file(file.id) is not None
    assert library.get_authorization(first.id).payload == b"fresh"
    assert len(library.list_sources()) == 1


def test_a_source_does_not_imply_an_authorization(library):
    source = library.create_source(LibrarySourceKind.LOCAL_FOLDER, "Plain", "/lib/plain")

    assert library.authorized_source_ids() == set()
    with pytest.raises(LibraryAuthorizationNotFoundError):
        library.get_authorization(source.id)


def test_set_authorization_replaces_or_adds(library):
    source = library.create_source(LibrarySourceKind.LOCAL_FOLDER, "Plain", "/lib/plain")

    library.set_authorization(source.id, *GRANT)
    first = library.get_authorization(source.id)
    library.set_authorization(source.id, "macos", "security_scoped_bookmark", b"second")
    second = library.get_authorization(source.id)

    assert second.payload == b"second" and second.created_at == first.created_at
    with pytest.raises(LibrarySourceNotFoundError):
        library.set_authorization("nope", *GRANT)


@pytest.mark.parametrize(
    "grant",
    [
        ("macos", "security_scoped_bookmark", b""),
        ("macos", "security_scoped_bookmark", b"x" * (MAX_AUTHORIZATION_BYTES + 1)),
        ("windows", "security_scoped_bookmark", b"x"),
        ("macos", "plain_path", b"x"),
    ],
)
def test_invalid_grants_are_rejected_and_nothing_is_created(library, grant):
    with pytest.raises(SessionError):
        library.authorize_local_folder("X", "/lib/x", *grant)

    assert library.list_sources() == []


def test_a_failed_replacement_keeps_the_previous_grant(library, connection):
    source, _ = library.authorize_local_folder("PHY215", "/lib/PHY215", *GRANT)
    connection.execute(
        "CREATE TRIGGER block_update BEFORE UPDATE ON library_source_authorizations "
        "BEGIN SELECT RAISE(ABORT, 'blocked'); END"
    )

    with pytest.raises(sqlite3.IntegrityError):
        library.set_authorization(source.id, "macos", "security_scoped_bookmark", b"new")

    assert library.get_authorization(source.id).payload == PAYLOAD


def test_a_failed_authorization_insert_rolls_back_the_new_source(library, connection):
    connection.execute(
        "CREATE TRIGGER block_insert BEFORE INSERT ON library_source_authorizations "
        "BEGIN SELECT RAISE(ABORT, 'blocked'); END"
    )

    with pytest.raises(sqlite3.IntegrityError):
        library.authorize_local_folder("PHY215", "/lib/PHY215", *GRANT)

    assert library.list_sources() == []  # no source row without its authorization


# --- regressions ---------------------------------------------------------------------


def test_course_deletion_keeps_the_source_authorization_and_files(library, courses):
    course = courses.create_course("Physics")
    source, _ = library.authorize_local_folder("PHY215", "/lib/PHY215", *GRANT)
    library.assign_source_to_course(source.id, course.id)
    file = library.register_or_update_file(source.id, "a.pdf")

    courses.delete_course(course.id)

    assert library.get_source(source.id).course_id is None
    assert library.get_authorization(source.id).payload == PAYLOAD
    assert library.get_file(file.id) is not None


def test_source_deletion_removes_the_authorization_and_files(library, connection, tmp_path):
    real = tmp_path / "folder"
    real.mkdir()
    (real / "note.txt").write_text("keep")
    source, _ = library.authorize_local_folder("PHY215", str(real), *GRANT)
    library.register_or_update_file(source.id, "note.txt")

    library.delete_source(source.id)

    assert connection.execute("SELECT COUNT(*) FROM library_source_authorizations").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM library_files").fetchone()[0] == 0
    assert (real / "note.txt").read_text() == "keep"


# --- schema --------------------------------------------------------------------------


def _names(connection):
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_fresh_database_is_v7_with_the_authorization_table(connection):
    assert get_schema_version(connection) == SCHEMA_VERSION == 7
    assert {"courses", "chats", "messages", "learning_memories", "library_sources", "library_files",
            "library_source_authorizations"} <= _names(connection)
    [fk] = list(connection.execute("PRAGMA foreign_key_list(library_source_authorizations)"))
    assert (fk["from"], fk["table"], fk["on_delete"]) == ("source_id", "library_sources", "CASCADE")
    columns = {r["name"]: r for r in connection.execute("PRAGMA table_info(library_source_authorizations)")}
    assert columns["source_id"]["pk"] == 1 and columns["authorization_data"]["type"] == "BLOB"


def test_one_authorization_per_source_and_constraints(connection):
    connection.execute(
        "INSERT INTO library_sources VALUES ('s1', NULL, 'local_folder', 'n', '/x', 't', 't')"
    )
    insert = (
        "INSERT INTO library_source_authorizations VALUES ('s1', ?, ?, ?, 't', 't')"
    )
    connection.execute(insert, ("macos", "security_scoped_bookmark", b"a"))
    for bad in [("macos", "security_scoped_bookmark", b"b"), ("linux", "security_scoped_bookmark", b"c"),
                ("macos", "other", b"d"), ("macos", "security_scoped_bookmark", b"")]:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert, bad)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO library_source_authorizations VALUES ('missing', 'macos', 'security_scoped_bookmark', x'01', 't', 't')")


def _create_v6_database(db_path):
    conn = open_database(db_path)
    conn.execute("DROP TABLE library_source_authorizations")
    conn.execute("PRAGMA user_version = 6")
    conn.commit()
    return conn


def _seed(conn):
    conn.execute("INSERT INTO courses VALUES ('c1', 'Physics', NULL, NULL, NULL, 't', 't')")
    conn.execute("INSERT INTO chats VALUES ('chat1', 'Chat', 'c1', 'homework', 'deep', 't', 't')")
    conn.execute("INSERT INTO messages (chat_id, role, content, created_at) VALUES ('chat1', 'user', 'hi', 't')")
    conn.execute("INSERT INTO learning_memories VALUES ('m1', 'c1', 'chat1', 'T', 'needs_review', 's', 'active', 't', 't')")
    conn.execute("INSERT INTO library_sources VALUES ('s1', 'c1', 'local_folder', 'Phys', '/x', 't', 't')")
    conn.execute(
        "INSERT INTO library_files (id, source_id, relative_path, display_name, created_at, updated_at) "
        "VALUES ('f1', 's1', 'a.pdf', 'a', 't', 't')"
    )
    conn.commit()


def test_v6_database_migrates_to_v7_without_inventing_authorizations(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v6_database(db_path)
    _seed(seed)
    seed.close()

    connection = open_database(db_path)
    try:
        assert get_schema_version(connection) == 7
        assert connection.execute("SELECT name FROM courses").fetchone()[0] == "Physics"
        assert connection.execute("SELECT content FROM messages").fetchone()[0] == "hi"
        assert connection.execute("SELECT summary FROM learning_memories").fetchone()[0] == "s"
        assert connection.execute("SELECT locator FROM library_sources").fetchone()[0] == "/x"
        assert connection.execute("SELECT relative_path FROM library_files").fetchone()[0] == "a.pdf"
        assert connection.execute("SELECT COUNT(*) FROM library_source_authorizations").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
    again = open_database(db_path)  # runs exactly once
    assert get_schema_version(again) == 7
    again.close()


def test_failed_v7_migration_leaves_the_v6_database_untouched(tmp_path):
    db_path = tmp_path / "studybot.db"
    seed = _create_v6_database(db_path)
    _seed(seed)
    seed.execute("CREATE TABLE library_source_authorizations (bogus INTEGER)")
    seed.commit()
    seed.close()

    with pytest.raises(sqlite3.OperationalError):
        open_database(db_path)

    verify = sqlite3.connect(db_path)
    assert verify.execute("PRAGMA user_version").fetchone()[0] == 6
    assert verify.execute("SELECT COUNT(*) FROM library_sources").fetchone()[0] == 1
    verify.close()


def test_v5_database_migrates_through_v6_to_v7(tmp_path):
    from tests.test_library_schema import _create_v5_database, _seed_v5

    db_path = tmp_path / "studybot.db"
    seed = _create_v5_database(db_path)
    _seed_v5(seed)
    seed.close()

    connection = open_database(db_path)
    try:
        assert get_schema_version(connection) == 7
        assert {"library_sources", "library_files", "library_source_authorizations"} <= _names(connection)
        assert connection.execute("SELECT summary FROM learning_memories").fetchone()[0] == "sum"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
