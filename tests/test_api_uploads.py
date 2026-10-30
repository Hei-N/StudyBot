import os
import sqlite3
import stat
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from studybot.api.server import create_app
from studybot.config.settings import Settings
from studybot.core.upload_store import is_stored_name
from tests.pdf_helpers import make_pdf
from tests.test_api_pdf_import import HEADERS, SpyExtractor, TOKEN


def make_client(tmp_path, extractor=None):
    settings = Settings.from_env(env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)})
    return TestClient(create_app(settings=settings, token=TOKEN, pdf_extractor=extractor))


@pytest.fixture
def extractor():
    return SpyExtractor()


@pytest.fixture
def client(tmp_path, extractor):
    with make_client(tmp_path, extractor) as c:
        c.data_dir = tmp_path
        yield c


def stage_copy_of(client, original):
    """What the native layer does: copy the user's file into private staging."""
    directory = client.data_dir / "ingest_staging"
    directory.mkdir(exist_ok=True)
    staging_id = str(uuid.uuid4())
    (directory / f"{staging_id}.pdf").write_bytes(original.read_bytes())
    return staging_id


def user_pdf(tmp_path, name="Lecture.pdf", pages=("Density formula", "Newton's second law"), **kwargs):
    folder = tmp_path / "Downloads"
    folder.mkdir(exist_ok=True)
    return make_pdf(folder / name, list(pages), **kwargs)


def upload(client, original, display_name=None):
    return client.post(
        "/api/v1/library/uploads/pdf",
        json={"stagingId": stage_copy_of(client, original), "displayName": display_name or original.name},
        headers=HEADERS,
    )


def private_files(client):
    directory = client.data_dir / "library_files"
    return sorted(directory.iterdir()) if directory.exists() else []


def db_count(client, table):
    connection = sqlite3.connect(client.data_dir / "studybot.db")
    try:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        connection.close()


# --- success -------------------------------------------------------------------------


def test_upload_creates_a_ready_file_with_a_private_copy(client, tmp_path):
    original = user_pdf(tmp_path)

    response = upload(client, original)

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "uploaded" and body["failureCode"] is None
    file = body["file"]
    assert (file["processingState"], file["pageCount"], file["textPageCount"]) == ("ready", 2, 2)
    assert file["displayName"] == "Lecture.pdf" and file["relativePath"] == "Lecture.pdf"
    [stored] = private_files(client)
    assert is_stored_name(stored.name) and stat.S_IMODE(stored.stat().st_mode) == 0o600
    assert db_count(client, "library_pages") == 2
    assert os.listdir(client.data_dir / "ingest_staging") == []  # staged copy discarded


def test_nothing_internal_is_exposed_through_the_api(client, tmp_path):
    original = user_pdf(tmp_path)
    uploaded = upload(client, original)
    listing = client.get("/api/v1/library/uploads", headers=HEADERS)
    [stored] = private_files(client)

    for response in (uploaded, listing):
        assert stored.name not in response.text and str(client.data_dir) not in response.text
        assert "library_files" not in response.text and str(tmp_path) not in response.text
    assert [f["displayName"] for f in listing.json()] == ["Lecture.pdf"]


def test_uploads_do_not_appear_as_folder_sources_and_the_source_cannot_be_removed(client, tmp_path):
    upload(client, user_pdf(tmp_path))
    connection = sqlite3.connect(client.data_dir / "studybot.db")
    uploads_id = connection.execute("SELECT id FROM library_sources WHERE kind = 'uploads'").fetchone()[0]
    connection.close()

    sources = client.get("/api/v1/library/sources", headers=HEADERS).json()
    removal = client.delete(f"/api/v1/library/sources/{uploads_id}", headers=HEADERS)
    files = client.get(f"/api/v1/library/sources/{uploads_id}/files", headers=HEADERS).json()

    assert sources == [] and removal.status_code == 422
    assert files[0]["relativePath"] == "Lecture.pdf"  # the private name stays hidden here too
    assert db_count(client, "library_files") == 1


def test_empty_pages_and_image_only_pdfs(client, tmp_path):
    mixed = upload(client, user_pdf(tmp_path, "mixed.pdf", pages=("text", "", "more"))).json()["file"]
    scan = upload(client, user_pdf(tmp_path, "scan.pdf", pages=("", ""), image_only=True)).json()["file"]

    assert (mixed["pageCount"], mixed["textPageCount"]) == (3, 2)
    assert (scan["processingState"], scan["pageCount"], scan["textPageCount"]) == ("ready", 2, 0)
    assert db_count(client, "library_pages") == 5


# --- failures leave nothing behind ---------------------------------------------------


def test_invalid_pdf_fails_without_leaving_records_or_copies(client, tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")

    body = upload(client, bad).json()

    assert body["outcome"] == "failed" and body["failureCode"] == "invalid_pdf" and body["file"] is None
    assert private_files(client) == [] and db_count(client, "library_files") == 0 and db_count(client, "library_pages") == 0
    assert os.listdir(client.data_dir / "ingest_staging") == []
    assert client.get("/api/v1/health", headers=HEADERS).status_code == 200


def test_password_protected_pdf_fails_cleanly(client, tmp_path):
    body = upload(client, user_pdf(tmp_path, "locked.pdf", pages=("secret",), password="pw")).json()

    assert (body["outcome"], body["failureCode"], body["file"]) == ("failed", "password_required", None)
    assert private_files(client) == [] and db_count(client, "library_files") == 0
    assert "secret" not in str(body)


def test_an_extractor_crash_fails_cleanly(tmp_path):
    with make_client(tmp_path, SpyExtractor(error=RuntimeError("boom /private/path"))) as client:
        client.data_dir = tmp_path
        response = upload(client, user_pdf(tmp_path))

        assert response.json()["outcome"] == "failed" and "boom" not in response.text
        assert private_files(client) == [] and db_count(client, "library_files") == 0


def test_a_database_failure_while_finishing_rolls_everything_back(client, tmp_path):
    connection = sqlite3.connect(client.data_dir / "studybot.db")
    connection.execute(
        "CREATE TRIGGER block_pages BEFORE INSERT ON library_pages BEGIN SELECT RAISE(ABORT, 'blocked'); END"
    )
    connection.commit()
    connection.close()

    body = upload(client, user_pdf(tmp_path)).json()

    assert body["outcome"] == "failed" and body["file"] is None
    assert private_files(client) == [] and db_count(client, "library_files") == 0 and db_count(client, "library_pages") == 0


def test_an_oversized_pdf_is_rejected_without_storing_anything(client, tmp_path, monkeypatch):
    from studybot.api import ingest

    monkeypatch.setattr(ingest, "MAX_PDF_BYTES", 10)

    response = upload(client, user_pdf(tmp_path))

    assert response.status_code == 422 and private_files(client) == []
    assert os.listdir(client.data_dir / "ingest_staging") == []


@pytest.mark.parametrize("bad_id", ["../x", "/etc/passwd", "nope", "a/b", ""])
def test_malformed_staging_ids_are_rejected(client, bad_id):
    response = client.post("/api/v1/library/uploads/pdf", json={"stagingId": bad_id, "displayName": "a.pdf"}, headers=HEADERS)

    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR"


def test_a_staging_symlink_is_not_followed(client, tmp_path):
    secret = user_pdf(tmp_path, "secret.pdf")
    directory = client.data_dir / "ingest_staging"
    directory.mkdir(exist_ok=True)
    staging_id = str(uuid.uuid4())
    (directory / f"{staging_id}.pdf").symlink_to(secret)

    response = client.post("/api/v1/library/uploads/pdf", json={"stagingId": staging_id, "displayName": "x.pdf"}, headers=HEADERS)

    assert response.status_code == 422 and secret.exists() and private_files(client) == []


def test_the_endpoints_require_the_token(client):
    for method, path in [("get", "/api/v1/library/uploads"), ("post", "/api/v1/library/uploads/pdf"),
                         ("delete", "/api/v1/library/uploads/x")]:
        assert getattr(client, method)(path).status_code == 401


# --- identity and duplicates ---------------------------------------------------------


def test_the_same_pdf_again_is_a_duplicate_and_not_reextracted(client, extractor, tmp_path):
    original = user_pdf(tmp_path)
    first = upload(client, original).json()
    second = upload(client, original, display_name="Renamed copy.pdf").json()

    assert (first["outcome"], second["outcome"]) == ("uploaded", "duplicate")
    assert second["file"]["id"] == first["file"]["id"] and second["file"]["displayName"] == "Lecture.pdf"
    assert extractor.calls == 1 and len(private_files(client)) == 1 and db_count(client, "library_pages") == 2
    assert os.listdir(client.data_dir / "ingest_staging") == []


def test_the_same_filename_with_different_content_is_a_separate_file(client, tmp_path):
    first = upload(client, user_pdf(tmp_path, "lecture.pdf", pages=("version one",))).json()["file"]
    second = upload(client, user_pdf(tmp_path, "lecture.pdf", pages=("version two", "extra"))).json()["file"]

    assert first["id"] != second["id"] and first["displayName"] == second["displayName"] == "lecture.pdf"
    assert len(private_files(client)) == 2 and len(client.get("/api/v1/library/uploads", headers=HEADERS).json()) == 2


def test_an_old_processing_version_copy_is_replaced_by_a_fresh_upload(tmp_path):
    original = user_pdf(tmp_path)
    with make_client(tmp_path, SpyExtractor()) as client:
        client.data_dir = tmp_path
        first = upload(client, original).json()["file"]
        [old_copy] = private_files(client)
    with make_client(tmp_path, SpyExtractor(version="pdf_text_v3")) as client:
        client.data_dir = tmp_path
        second = upload(client, original).json()

        assert second["outcome"] == "uploaded" and second["file"]["processingVersion"] == "pdf_text_v3"
        assert second["file"]["id"] != first["id"]
        assert not old_copy.exists() and len(private_files(client)) == 1
        assert len(client.get("/api/v1/library/uploads", headers=HEADERS).json()) == 1


# --- original file safety ------------------------------------------------------------


def test_the_original_file_is_never_modified_and_may_be_deleted_afterwards(client, tmp_path):
    original = user_pdf(tmp_path)
    before = (original.read_bytes(), original.stat().st_mtime_ns)

    file = upload(client, original).json()["file"]

    assert (original.read_bytes(), original.stat().st_mtime_ns) == before
    original.unlink()  # the user deletes their copy
    assert client.get("/api/v1/library/uploads", headers=HEADERS).json()[0]["id"] == file["id"]
    assert len(private_files(client)) == 1 and db_count(client, "library_pages") == 2


def test_removing_an_upload_deletes_record_pages_and_private_copy_only(client, tmp_path):
    original = user_pdf(tmp_path)
    file = upload(client, original).json()["file"]

    response = client.delete(f"/api/v1/library/uploads/{file['id']}", headers=HEADERS)

    assert response.status_code == 204
    assert private_files(client) == [] and db_count(client, "library_files") == 0 and db_count(client, "library_pages") == 0
    assert original.exists() and client.get("/api/v1/library/uploads", headers=HEADERS).json() == []


def test_removing_an_unknown_upload_or_a_folder_file_is_refused(client, tmp_path):
    folder_source = client.post(
        "/api/v1/library/sources/local-folder",
        json={"displayName": "F", "locator": "/f", "authorization": {
            "platform": "macos", "kind": "security_scoped_bookmark", "payload": "AQ=="}},
        headers=HEADERS,
    ).json()["id"]
    staged = stage_copy_of(client, user_pdf(tmp_path, "folder.pdf"))
    folder_file = client.post(f"/api/v1/library/sources/{folder_source}/imports/pdf",
                              json={"stagingId": staged, "relativePath": "folder.pdf"}, headers=HEADERS).json()["file"]

    assert client.delete("/api/v1/library/uploads/nope", headers=HEADERS).status_code == 404
    assert client.delete(f"/api/v1/library/uploads/{folder_file['id']}", headers=HEADERS).status_code == 404
    assert len(client.get(f"/api/v1/library/sources/{folder_source}/files", headers=HEADERS).json()) == 1


def test_removing_a_folder_source_still_works_and_keeps_uploads(client, tmp_path):
    upload(client, user_pdf(tmp_path))
    source = client.post(
        "/api/v1/library/sources/local-folder",
        json={"displayName": "F", "locator": "/f", "authorization": {
            "platform": "macos", "kind": "security_scoped_bookmark", "payload": "AQ=="}},
        headers=HEADERS,
    ).json()["id"]

    assert client.delete(f"/api/v1/library/sources/{source}", headers=HEADERS).status_code == 204

    assert len(client.get("/api/v1/library/uploads", headers=HEADERS).json()) == 1


# --- startup recovery and cleanup ----------------------------------------------------


def test_startup_cleans_interrupted_uploads_and_orphaned_private_files(tmp_path):
    from studybot.app import StudyBotApp

    settings = Settings.from_env(env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)})
    app = StudyBotApp(settings)
    digest = "a" * 64
    plan = app.library.prepare_upload("crashed.pdf", size_bytes=1, content_hash=digest, processing_version="pdf_text_v1")
    app.close()  # the process dies mid-upload
    store_dir = tmp_path / "library_files"
    store_dir.mkdir()
    (store_dir / plan.stored_name).write_bytes(b"%PDF half")
    orphan = store_dir / f"{uuid.uuid4()}.pdf"
    orphan.write_bytes(b"%PDF orphan")
    partial = store_dir / f"{uuid.uuid4()}.pdf.part"
    partial.write_bytes(b"x")
    foreign = store_dir / "readme.txt"
    foreign.write_text("keep")

    with make_client(tmp_path) as client:
        client.data_dir = tmp_path
        assert client.get("/api/v1/library/uploads", headers=HEADERS).json() == []
        assert private_files(client) == [foreign]
        assert db_count(client, "library_files") == 0


def test_completed_uploads_survive_a_restart(tmp_path):
    original = user_pdf(tmp_path)
    with make_client(tmp_path) as client:
        client.data_dir = tmp_path
        file = upload(client, original).json()["file"]
    original.unlink()

    with make_client(tmp_path) as client:
        client.data_dir = tmp_path
        files = client.get("/api/v1/library/uploads", headers=HEADERS).json()
        assert [f["id"] for f in files] == [file["id"]] and len(private_files(client)) == 1
        assert db_count(client, "library_pages") == 2


# --- responsiveness ------------------------------------------------------------------


def test_uploads_do_not_block_the_engine_thread(tmp_path):
    import threading

    started = threading.Event()
    with make_client(tmp_path, SpyExtractor(delay=2.0, started=started)) as client:
        client.data_dir = tmp_path
        original = user_pdf(tmp_path)
        result = {}
        worker = threading.Thread(target=lambda: result.update(r=upload(client, original)))
        worker.start()
        assert started.wait(10)

        began = time.monotonic()
        health = client.get("/api/v1/health", headers=HEADERS)
        chat = client.post("/api/v1/chats", json={}, headers=HEADERS)
        elapsed = time.monotonic() - began
        busy = worker.is_alive()
        worker.join(20)

    assert busy and elapsed < 1.5 and health.status_code == 200 and chat.status_code == 201
    assert result["r"].json()["outcome"] == "uploaded"
