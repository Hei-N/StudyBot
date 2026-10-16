import base64
import hashlib
import sqlite3
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from studybot.api.server import create_app
from studybot.config.settings import Settings
from studybot.core.pdf_extractor import PdfExtractor
from tests.pdf_helpers import make_pdf

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
BOOKMARK = base64.b64encode(b"opaque-bookmark").decode()


class SpyExtractor(PdfExtractor):
    """Counts calls; can be slowed, failed or given another processing version."""

    def __init__(self, version=None, delay=0.0, error=None, started=None):
        self.calls = 0
        self.delay = delay
        self.error = error
        self.started = started
        if version:
            self.processing_version = version

    def extract(self, path):
        self.calls += 1
        if self.started:
            self.started.set()
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        return super().extract(path)


def make_client(tmp_path, extractor):
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


@pytest.fixture
def source(client):
    response = client.post(
        "/api/v1/library/sources/local-folder",
        json={"displayName": "PHY215", "locator": "/library/PHY215",
              "authorization": {"platform": "macos", "kind": "security_scoped_bookmark", "payload": BOOKMARK}},
        headers=HEADERS,
    )
    return response.json()["id"]


def stage_pdf(client, tmp_path, pages=("Density formula: rho = m / V", "Newton: F = ma"), **kwargs):
    staging_id = str(uuid.uuid4())
    staging_dir = client.data_dir / "ingest_staging"
    staging_dir.mkdir(exist_ok=True)
    make_pdf(staging_dir / f"{staging_id}.pdf", list(pages), **kwargs)
    return staging_id


def restage_same_bytes(client, staging_id):
    """A second staged copy with identical bytes (separately generated PDFs differ in embedded IDs)."""
    directory = client.data_dir / "ingest_staging"
    copy = str(uuid.uuid4())
    (directory / f"{copy}.pdf").write_bytes((directory / f"{staging_id}.pdf").read_bytes())
    return copy


def do_import(client, source_id, staging_id, path="Week 2/Lecture.pdf", name=None):
    return client.post(
        f"/api/v1/library/sources/{source_id}/imports/pdf",
        json={"stagingId": staging_id, "relativePath": path, "displayName": name},
        headers=HEADERS,
    )


def pages_in_db(client, file_id):
    connection = sqlite3.connect(client.data_dir / "studybot.db")
    rows = connection.execute(
        "SELECT page_number, text_content FROM library_pages WHERE file_id = ? ORDER BY page_number", (file_id,)
    ).fetchall()
    connection.close()
    return rows


def staged_files(client):
    return list((client.data_dir / "ingest_staging").iterdir())


# --- basic import --------------------------------------------------------------------


def test_import_extracts_pages_and_marks_the_file_ready(client, source, tmp_path):
    response = do_import(client, source, stage_pdf(client, tmp_path))

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "imported"
    file = body["file"]
    assert file["processingState"] == "ready" and file["pageCount"] == 2 and file["textPageCount"] == 2
    assert file["processingVersion"] == "pdf_text_v1" and file["indexedAt"] and file["failureCode"] is None
    assert file["relativePath"] == "Week 2/Lecture.pdf" and file["displayName"] == "Lecture.pdf"
    rows = pages_in_db(client, file["id"])
    assert [n for n, _ in rows] == [1, 2] and "rho = m / V" in rows[0][1] and "F = ma" in rows[1][1]


def test_the_staged_copy_is_removed_after_import(client, source, tmp_path):
    do_import(client, source, stage_pdf(client, tmp_path))

    assert staged_files(client) == []


def test_file_list_has_no_text_or_paths(client, source, tmp_path):
    do_import(client, source, stage_pdf(client, tmp_path))

    response = client.get(f"/api/v1/library/sources/{source}/files", headers=HEADERS)

    [file] = response.json()
    assert file["pageCount"] == 2
    assert set(file) == {"id", "sourceId", "relativePath", "displayName", "extension", "sizeBytes", "processingState",
                         "failureCode", "pageCount", "textPageCount", "processingVersion", "indexedAt", "updatedAt"}
    assert "rho" not in response.text and "/library" not in response.text


def test_files_of_an_unknown_source(client):
    response = client.get("/api/v1/library/sources/nope/files", headers=HEADERS)

    assert response.status_code == 404 and response.json()["code"] == "LIBRARY_SOURCE_NOT_FOUND"


def test_staging_directory_endpoint_points_inside_the_data_directory(client):
    response = client.get("/api/v1/library/ingest-staging", headers=HEADERS)

    assert response.json()["path"] == str(client.data_dir / "ingest_staging")


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/api/v1/library/sources/x/files"), ("get", "/api/v1/library/ingest-staging"),
     ("post", "/api/v1/library/sources/x/imports/pdf")],
)
def test_new_endpoints_require_the_token(client, method, path):
    assert getattr(client, method)(path).status_code == 401


# --- incremental processing ----------------------------------------------------------


def test_same_pdf_twice_runs_the_extractor_once(client, extractor, source, tmp_path):
    staged = stage_pdf(client, tmp_path)
    again = restage_same_bytes(client, staged)
    first = do_import(client, source, staged, path="a.pdf").json()
    second = do_import(client, source, again, path="a.pdf").json()

    assert (first["outcome"], second["outcome"]) == ("imported", "unchanged")
    assert extractor.calls == 1
    assert second["file"]["id"] == first["file"]["id"]
    assert second["file"]["indexedAt"] == first["file"]["indexedAt"]
    assert len(pages_in_db(client, first["file"]["id"])) == 2
    assert staged_files(client) == []


def test_changed_pdf_at_the_same_path_is_reextracted_in_place(client, extractor, source, tmp_path):
    first = do_import(client, source, stage_pdf(client, tmp_path, pages=["old one", "old two"]), path="a.pdf").json()
    second = do_import(client, source, stage_pdf(client, tmp_path, pages=["new one", "new two", "new three"]),
                       path="a.pdf").json()

    assert second["outcome"] == "imported" and extractor.calls == 2
    assert second["file"]["id"] == first["file"]["id"]
    assert second["file"]["pageCount"] == 3 and second["file"]["processingState"] == "ready"
    rows = pages_in_db(client, first["file"]["id"])
    assert [n for n, _ in rows] == [1, 2, 3] and all("new" in t for _, t in rows)
    assert len(client.get(f"/api/v1/library/sources/{source}/files", headers=HEADERS).json()) == 1


def test_a_new_processing_version_forces_reprocessing(tmp_path):
    first_extractor = SpyExtractor()
    with make_client(tmp_path, first_extractor) as client:
        client.data_dir = tmp_path
        sid = client.post("/api/v1/library/sources/local-folder",
                          json={"displayName": "S", "locator": "/s", "authorization": {
                              "platform": "macos", "kind": "security_scoped_bookmark", "payload": BOOKMARK}},
                          headers=HEADERS).json()["id"]
        staged = stage_pdf(client, tmp_path)
        pdf_bytes = (tmp_path / "ingest_staging" / f"{staged}.pdf").read_bytes()
        first = do_import(client, sid, staged, path="a.pdf").json()

    upgraded = SpyExtractor(version="pdf_text_v2")
    with make_client(tmp_path, upgraded) as client:
        client.data_dir = tmp_path
        same_bytes = str(uuid.uuid4())
        (tmp_path / "ingest_staging" / f"{same_bytes}.pdf").write_bytes(pdf_bytes)  # identical content
        second = do_import(client, sid, same_bytes, path="a.pdf").json()
        rows = pages_in_db(client, first["file"]["id"])

    assert second["outcome"] == "imported" and upgraded.calls == 1  # same hash, new version: reprocessed
    assert second["file"]["id"] == first["file"]["id"]
    assert second["file"]["processingVersion"] == "pdf_text_v2"
    assert second["file"]["indexedAt"] != first["file"]["indexedAt"]
    assert len(rows) == 2


def test_hash_unchanged_with_a_new_modification_time_is_not_reextracted(client, extractor, source, tmp_path):
    first_id = stage_pdf(client, tmp_path)
    second_id = restage_same_bytes(client, first_id)
    do_import(client, source, first_id, path="a.pdf")

    result = do_import(client, source, second_id, path="a.pdf").json()

    assert result["outcome"] == "unchanged" and extractor.calls == 1


# --- extraction outcomes -------------------------------------------------------------


def test_image_only_pdf_becomes_ready_without_text(client, source, tmp_path):
    result = do_import(client, source, stage_pdf(client, tmp_path, pages=["", ""], image_only=True)).json()

    assert result["outcome"] == "imported"
    assert (result["file"]["processingState"], result["file"]["pageCount"], result["file"]["textPageCount"]) == ("ready", 2, 0)
    assert len(pages_in_db(client, result["file"]["id"])) == 2


def test_password_protected_pdf_fails_cleanly(client, source, tmp_path):
    result = do_import(client, source, stage_pdf(client, tmp_path, pages=["secret"], password="pw")).json()

    assert result["outcome"] == "failed"
    assert (result["file"]["processingState"], result["file"]["failureCode"]) == ("failed", "password_required")
    assert pages_in_db(client, result["file"]["id"]) == [] and staged_files(client) == []
    assert "secret" not in str(result) and "pw" not in str(result["file"])


def test_invalid_pdf_fails_cleanly_and_retry_with_a_good_pdf_works(client, source, tmp_path):
    bad = str(uuid.uuid4())
    (client.data_dir / "ingest_staging").mkdir(exist_ok=True)
    (client.data_dir / "ingest_staging" / f"{bad}.pdf").write_bytes(b"not a pdf")

    failed = do_import(client, source, bad, path="a.pdf").json()
    retried = do_import(client, source, stage_pdf(client, tmp_path), path="a.pdf").json()

    assert failed["file"]["failureCode"] == "invalid_pdf" and failed["outcome"] == "failed"
    assert retried["outcome"] == "imported" and retried["file"]["id"] == failed["file"]["id"]
    assert retried["file"]["processingState"] == "ready" and retried["file"]["failureCode"] is None


def test_an_extractor_exception_fails_the_file_and_leaves_the_engine_usable(tmp_path):
    extractor = SpyExtractor(error=RuntimeError("boom: /secret/path"))
    with make_client(tmp_path, extractor) as client:
        client.data_dir = tmp_path
        sid = client.post("/api/v1/library/sources/local-folder",
                          json={"displayName": "S", "locator": "/s", "authorization": {
                              "platform": "macos", "kind": "security_scoped_bookmark", "payload": BOOKMARK}},
                          headers=HEADERS).json()["id"]

        result = do_import(client, sid, stage_pdf(client, tmp_path), path="a.pdf")

        body = result.json()
        assert result.status_code == 200 and body["outcome"] == "failed"
        assert body["file"]["failureCode"] == "extraction_failed"
        assert "boom" not in result.text and "secret" not in result.text
        assert pages_in_db(client, body["file"]["id"]) == [] and staged_files(client) == []
        assert client.get("/api/v1/health", headers=HEADERS).status_code == 200
        assert client.post("/api/v1/chats", json={}, headers=HEADERS).status_code == 201


# --- validation and security ---------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["../x", "../../etc/passwd", "/etc/passwd", "nope", "a/b", ""])
def test_malformed_staging_ids_are_rejected(client, source, bad_id):
    response = do_import(client, source, bad_id)

    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR"


def test_missing_staged_file(client, source):
    response = do_import(client, source, str(uuid.uuid4()))

    assert response.status_code == 404 and response.json()["code"] == "LIBRARY_STAGING_NOT_FOUND"


def test_a_symlink_in_staging_is_never_followed(client, source, tmp_path):
    outside = tmp_path / "outside.pdf"
    make_pdf(outside, ["user file"])
    staging_dir = client.data_dir / "ingest_staging"
    staging_dir.mkdir(exist_ok=True)
    staging_id = str(uuid.uuid4())
    (staging_dir / f"{staging_id}.pdf").symlink_to(outside)

    response = do_import(client, source, staging_id)

    assert response.status_code == 422
    assert outside.exists()  # the user file was neither read into the library nor deleted
    assert client.get(f"/api/v1/library/sources/{source}/files", headers=HEADERS).json() == []


def test_a_directory_in_staging_is_rejected(client, source):
    staging_dir = client.data_dir / "ingest_staging"
    staging_dir.mkdir(exist_ok=True)
    staging_id = str(uuid.uuid4())
    (staging_dir / f"{staging_id}.pdf").mkdir()

    assert do_import(client, source, staging_id).status_code == 422


def test_unknown_source_and_source_without_authorization(client, source, tmp_path):
    missing = do_import(client, "no-such-source", stage_pdf(client, tmp_path))
    plain = client.post("/api/v1/library/sources/local-folder", json={
        "displayName": "x", "locator": "/x",
        "authorization": {"platform": "macos", "kind": "security_scoped_bookmark", "payload": BOOKMARK}}, headers=HEADERS).json()
    connection = sqlite3.connect(client.data_dir / "studybot.db")
    connection.execute("DELETE FROM library_source_authorizations WHERE source_id = ?", (plain["id"],))
    connection.commit()
    connection.close()
    unauthorized = do_import(client, plain["id"], stage_pdf(client, tmp_path))

    assert missing.status_code == 404 and missing.json()["code"] == "LIBRARY_SOURCE_NOT_FOUND"
    assert unauthorized.status_code == 404 and unauthorized.json()["code"] == "LIBRARY_AUTHORIZATION_NOT_FOUND"
    assert staged_files(client) == []  # staged copies are discarded even when rejected


@pytest.mark.parametrize("path", ["../secret.pdf", "/abs/file.pdf", "notes.txt", "folder/file.docx", ""])
def test_unsafe_or_non_pdf_relative_paths_are_rejected(client, source, tmp_path, path):
    response = do_import(client, source, stage_pdf(client, tmp_path), path=path)

    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR"
    assert client.get(f"/api/v1/library/sources/{source}/files", headers=HEADERS).json() == []


def test_an_oversized_pdf_is_rejected_without_reading_it(client, source, tmp_path, monkeypatch):
    from studybot.api import ingest

    monkeypatch.setattr(ingest, "MAX_PDF_BYTES", 10)

    response = do_import(client, source, stage_pdf(client, tmp_path))

    assert response.status_code == 422 and staged_files(client) == []


def test_errors_never_contain_paths_or_document_text(client, source, tmp_path):
    response = do_import(client, source, "../../etc/passwd")

    assert "/etc" not in response.text and "Traceback" not in response.text


# --- deletion regressions ------------------------------------------------------------


def test_deleting_the_source_removes_files_and_pages(client, source, tmp_path):
    real = tmp_path / "user-folder"
    real.mkdir()
    (real / "a.pdf").write_bytes(b"user's real pdf")
    file_id = do_import(client, source, stage_pdf(client, tmp_path), path="a.pdf").json()["file"]["id"]

    assert client.delete(f"/api/v1/library/sources/{source}", headers=HEADERS).status_code == 204

    assert pages_in_db(client, file_id) == []
    assert (real / "a.pdf").read_bytes() == b"user's real pdf"


def test_deleting_a_course_keeps_pages(client, source, tmp_path):
    course = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()["id"]
    connection = sqlite3.connect(client.data_dir / "studybot.db")
    connection.execute("UPDATE library_sources SET course_id = ? WHERE id = ?", (course, source))
    connection.commit()
    connection.close()
    file_id = do_import(client, source, stage_pdf(client, tmp_path), path="a.pdf").json()["file"]["id"]

    assert client.delete(f"/api/v1/courses/{course}", headers=HEADERS).status_code == 204

    assert len(pages_in_db(client, file_id)) == 2
    assert client.get("/api/v1/library/sources", headers=HEADERS).json()[0]["courseId"] is None


# --- responsiveness ------------------------------------------------------------------


def test_extraction_does_not_block_the_engine_thread(tmp_path):
    started = threading.Event()
    extractor = SpyExtractor(delay=2.0, started=started)
    with make_client(tmp_path, extractor) as client:
        client.data_dir = tmp_path
        sid = client.post("/api/v1/library/sources/local-folder",
                          json={"displayName": "S", "locator": "/s", "authorization": {
                              "platform": "macos", "kind": "security_scoped_bookmark", "payload": BOOKMARK}},
                          headers=HEADERS).json()["id"]
        staging_id = stage_pdf(client, tmp_path)
        result = {}
        worker = threading.Thread(target=lambda: result.update(r=do_import(client, sid, staging_id, path="a.pdf")))
        worker.start()
        assert started.wait(10)

        began = time.monotonic()
        health = client.get("/api/v1/health", headers=HEADERS)
        chat = client.post("/api/v1/chats", json={}, headers=HEADERS)
        sources = client.get("/api/v1/library/sources", headers=HEADERS)
        elapsed = time.monotonic() - began
        still_running = worker.is_alive()
        worker.join(20)

    assert still_running and elapsed < 1.5
    assert health.status_code == 200 and chat.status_code == 201 and sources.status_code == 200
    assert result["r"].json()["outcome"] == "imported"


def test_startup_removes_old_staged_orphans_but_nothing_else(tmp_path):
    import os

    staging_dir = tmp_path / "ingest_staging"
    staging_dir.mkdir()
    orphan = staging_dir / f"{uuid.uuid4()}.pdf"
    orphan.write_bytes(b"x")
    keep = staging_dir / "notes.txt"
    keep.write_text("keep")
    old = time.time() - 48 * 3600
    for path in (orphan, keep):
        os.utime(path, (old, old))

    with make_client(tmp_path, SpyExtractor()):
        pass

    assert not orphan.exists() and keep.exists()
