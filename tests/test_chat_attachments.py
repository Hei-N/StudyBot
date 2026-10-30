import sqlite3
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from studybot.api.server import create_app
from studybot.config.settings import Settings
from tests.pdf_helpers import make_pdf
from tests.test_api_pdf_import import HEADERS, TOKEN, SpyExtractor
from tests.test_api_uploads import stage_copy_of, user_pdf


def make_client(tmp_path, extractor=None):
    settings = Settings.from_env(env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)})
    return TestClient(create_app(settings=settings, token=TOKEN, pdf_extractor=extractor))


@pytest.fixture
def client(tmp_path):
    with make_client(tmp_path, SpyExtractor()) as c:
        c.data_dir = tmp_path
        yield c


def chat_upload(client, original, *, save_to_library=False, name=None):
    response = client.post(
        "/api/v1/library/uploads/pdf",
        json={"stagingId": stage_copy_of(client, original), "displayName": name or original.name,
              "saveToLibrary": save_to_library},
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    return response.json()


def new_chat(client):
    return client.post("/api/v1/chats", json={}, headers=HEADERS).json()["id"]


def send(client, chat_id, content="Help me with this PDF.", attachment_ids=None):
    payload = {"type": "send_message", "chat_id": chat_id, "content": content}
    if attachment_ids is not None:
        payload["attachment_ids"] = attachment_ids
    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json(payload)
        events = []
        while True:
            event = ws.receive_json()
            events.append(event)
            if event["type"] in ("message_completed", "error"):
                return events


def messages(client, chat_id):
    return client.get(f"/api/v1/chats/{chat_id}/messages", headers=HEADERS).json()


def db(client, sql, *args):
    connection = sqlite3.connect(client.data_dir / "studybot.db")
    try:
        return connection.execute(sql, args).fetchall()
    finally:
        connection.close()


def private_files(client):
    directory = client.data_dir / "library_files"
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


def library_listing(client):
    return client.get("/api/v1/library/uploads", headers=HEADERS).json()


# --- uploads for chat: kept out of the Study Library ---------------------------------


def test_a_chat_upload_is_ready_but_not_listed_in_the_study_library(client, tmp_path):
    body = chat_upload(client, user_pdf(tmp_path))

    assert body["outcome"] == "uploaded" and body["file"]["processingState"] == "ready"
    assert body["file"]["pageCount"] == 2
    assert library_listing(client) == []
    assert len(private_files(client)) == 1


def test_a_library_upload_of_the_same_bytes_adds_the_existing_copy_without_extracting_again(tmp_path):
    extractor = SpyExtractor()
    with make_client(tmp_path, extractor) as client:
        client.data_dir = tmp_path
        original = user_pdf(tmp_path)
        first = chat_upload(client, original)
        second = chat_upload(client, original, save_to_library=True)

        assert second["outcome"] == "uploaded" and second["file"]["id"] == first["file"]["id"]
        assert extractor.calls == 1 and len(private_files(client)) == 1
        assert [f["id"] for f in library_listing(client)] == [first["file"]["id"]]


def test_a_chat_upload_of_a_library_file_reuses_it_and_it_stays_in_the_library(client, tmp_path):
    original = user_pdf(tmp_path)
    kept = chat_upload(client, original, save_to_library=True)

    again = chat_upload(client, original, save_to_library=False)

    assert again["outcome"] == "duplicate" and again["file"]["id"] == kept["file"]["id"]
    assert [f["id"] for f in library_listing(client)] == [kept["file"]["id"]]


# --- sending with attachments --------------------------------------------------------


def test_text_only_messages_are_unchanged(client):
    chat_id = new_chat(client)

    events = send(client, chat_id, "plain question")

    assert events[-1]["type"] == "message_completed"
    stored = messages(client, chat_id)
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert all(m["attachments"] == [] for m in stored)


def test_a_message_stores_its_attachment_and_history_returns_it(client, tmp_path):
    file = chat_upload(client, user_pdf(tmp_path, "Lecture 5.pdf"))["file"]
    chat_id = new_chat(client)

    events = send(client, chat_id, "Help me with this PDF.", [file["id"]])

    assert events[-1]["type"] == "message_completed"
    user, assistant = messages(client, chat_id)
    assert user["content"] == "Help me with this PDF." and assistant["attachments"] == []
    [attachment] = user["attachments"]
    assert attachment["fileId"] == file["id"] and attachment["displayName"] == "Lecture 5.pdf"
    assert (attachment["pageCount"], attachment["textPageCount"], attachment["processingState"]) == (2, 2, "ready")
    assert set(attachment) == {"id", "fileId", "displayName", "pageCount", "textPageCount", "processingState"}


def test_the_message_text_is_what_the_model_gets_and_no_pdf_text_is_added(client, tmp_path):
    file = chat_upload(client, user_pdf(tmp_path, pages=("SECRET-PAGE-TEXT one", "two")))["file"]
    chat_id = new_chat(client)

    send(client, chat_id, "Summarize", [file["id"]])

    user, assistant = messages(client, chat_id)
    assert user["content"] == "Summarize"
    assert "SECRET-PAGE-TEXT" not in assistant["content"]  # the mock echoes what it was given


def test_several_attachments_on_one_message(client, tmp_path):
    ids = [chat_upload(client, user_pdf(tmp_path, f"f{n}.pdf", pages=(f"page of file {n}",)))["file"]["id"]
           for n in range(3)]
    chat_id = new_chat(client)

    send(client, chat_id, "three files", ids)

    user = messages(client, chat_id)[0]
    assert [a["fileId"] for a in user["attachments"]] == ids
    assert [a["displayName"] for a in user["attachments"]] == ["f0.pdf", "f1.pdf", "f2.pdf"]


def test_duplicate_ids_are_merged_and_the_limit_is_five(client, tmp_path):
    ids = [chat_upload(client, user_pdf(tmp_path, f"f{n}.pdf", pages=(f"file {n}",)))["file"]["id"] for n in range(6)]
    chat_id = new_chat(client)

    merged = send(client, chat_id, "dupes", [ids[0], ids[0], ids[1]])
    too_many = send(client, chat_id, "six", ids)

    assert merged[-1]["type"] == "message_completed"
    assert [a["fileId"] for a in messages(client, chat_id)[0]["attachments"]] == [ids[0], ids[1]]
    assert too_many[-1]["type"] == "error" and too_many[-1]["code"] == "VALIDATION_ERROR"
    assert len(messages(client, chat_id)) == 2  # the rejected send created nothing


@pytest.mark.parametrize("bad", [["no-such-file"], [42], "not-a-list"])
def test_invalid_attachment_ids_are_rejected_before_anything_is_stored(client, bad):
    chat_id = new_chat(client)

    events = send(client, chat_id, "hello", bad)

    assert events[-1]["type"] == "error"
    assert events[-1]["code"] in ("ATTACHMENT_NOT_FOUND", "VALIDATION_ERROR")
    assert "message_started" not in [e["type"] for e in events]
    assert messages(client, chat_id) == []


def test_only_finished_uploads_can_be_attached(client, tmp_path):
    chat_id = new_chat(client)
    # An upload still being processed (state indexing) is not attachable.
    connection = sqlite3.connect(client.data_dir / "studybot.db")
    done = chat_upload(client, user_pdf(tmp_path))["file"]["id"]
    connection.execute("UPDATE library_files SET processing_state = 'indexing' WHERE id = ?", (done,))
    connection.commit()
    connection.close()

    events = send(client, chat_id, "too early", [done])

    assert events[-1]["code"] == "ATTACHMENT_NOT_FOUND" and messages(client, chat_id) == []


def test_a_folder_source_file_cannot_be_attached(client, tmp_path):
    source = client.post(
        "/api/v1/library/sources/local-folder",
        json={"displayName": "F", "locator": "/f", "authorization": {
            "platform": "macos", "kind": "security_scoped_bookmark", "payload": "AQ=="}},
        headers=HEADERS,
    ).json()["id"]
    imported = client.post(
        f"/api/v1/library/sources/{source}/imports/pdf",
        json={"stagingId": stage_copy_of(client, user_pdf(tmp_path, "folder.pdf")), "relativePath": "folder.pdf"},
        headers=HEADERS,
    ).json()["file"]
    chat_id = new_chat(client)

    events = send(client, chat_id, "x", [imported["id"]])

    assert events[-1]["code"] == "ATTACHMENT_NOT_FOUND"


def test_attachments_stay_with_their_own_chat(client, tmp_path):
    file = chat_upload(client, user_pdf(tmp_path))["file"]["id"]
    first, second = new_chat(client), new_chat(client)

    send(client, first, "with file", [file])
    send(client, second, "without file")

    assert len(messages(client, first)[0]["attachments"]) == 1
    assert messages(client, second)[0]["attachments"] == []


def test_the_message_and_its_attachments_are_saved_together(client, tmp_path):
    chat_id = new_chat(client)
    chat_upload(client, user_pdf(tmp_path))

    connection = sqlite3.connect(client.data_dir / "studybot.db")
    connection.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError), connection:  # one transaction: the message rolls back too
        cursor = connection.execute(
            "INSERT INTO messages (chat_id, role, content, created_at) VALUES (?, 'user', 'x', 't')", (chat_id,)
        )
        connection.execute(
            "INSERT INTO message_attachments (message_id, file_id, created_at) VALUES (?, 'missing-file-id', 't')",
            (cursor.lastrowid,),
        )
    connection.close()
    assert messages(client, chat_id) == []


def test_attachments_survive_a_restart(tmp_path):
    original = user_pdf(tmp_path)
    with make_client(tmp_path, SpyExtractor()) as client:
        client.data_dir = tmp_path
        file = chat_upload(client, original)["file"]
        chat_id = new_chat(client)
        send(client, chat_id, "remember me", [file["id"]])
    original.unlink()

    with make_client(tmp_path, SpyExtractor()) as client:
        client.data_dir = tmp_path
        [attachment] = messages(client, chat_id)[0]["attachments"]
        assert attachment["fileId"] == file["id"] and len(private_files(client)) == 1


# --- ownership and cleanup -----------------------------------------------------------


def test_removing_a_pending_chat_upload_deletes_it_but_never_the_original(client, tmp_path):
    original = user_pdf(tmp_path)
    file = chat_upload(client, original)["file"]

    response = client.delete(f"/api/v1/library/attachments/{file['id']}", headers=HEADERS)

    assert response.status_code == 204
    assert private_files(client) == [] and db(client, "SELECT COUNT(*) FROM library_files WHERE in_library = 0") == [(0,)]
    assert db(client, "SELECT COUNT(*) FROM library_pages") == [(0,)]
    assert original.exists()


def test_discarding_never_touches_library_files_or_files_already_attached(client, tmp_path):
    kept = chat_upload(client, user_pdf(tmp_path, "kept.pdf", pages=("kept",)), save_to_library=True)["file"]
    attached = chat_upload(client, user_pdf(tmp_path, "attached.pdf", pages=("attached",)))["file"]
    send(client, new_chat(client), "with file", [attached["id"]])

    for file in (kept, attached):
        assert client.delete(f"/api/v1/library/attachments/{file['id']}", headers=HEADERS).status_code == 204

    assert len(private_files(client)) == 2 and db(client, "SELECT COUNT(*) FROM library_files") == [(2,)]
    assert client.delete("/api/v1/library/attachments/nope", headers=HEADERS).status_code == 204


def test_deleting_a_chat_removes_chat_only_files_that_lost_their_last_reference(client, tmp_path):
    only = chat_upload(client, user_pdf(tmp_path, "only.pdf", pages=("only",)))["file"]
    shared = chat_upload(client, user_pdf(tmp_path, "shared.pdf", pages=("shared",)))["file"]
    kept = chat_upload(client, user_pdf(tmp_path, "kept.pdf", pages=("kept",)), save_to_library=True)["file"]
    first, second = new_chat(client), new_chat(client)
    send(client, first, "a", [only["id"], shared["id"], kept["id"]])
    send(client, second, "b", [shared["id"]])

    assert client.delete(f"/api/v1/chats/{first}", headers=HEADERS).status_code == 204

    remaining = {r[0] for r in db(client, "SELECT display_name FROM library_files")}
    assert remaining == {"shared.pdf", "kept.pdf"}  # the only reference to only.pdf was deleted with the chat
    assert len(private_files(client)) == 2
    assert [a["displayName"] for a in messages(client, second)[0]["attachments"]] == ["shared.pdf"]


def test_clearing_a_chat_releases_its_chat_only_files(client, tmp_path):
    file = chat_upload(client, user_pdf(tmp_path))["file"]
    chat_id = new_chat(client)
    send(client, chat_id, "a", [file["id"]])

    assert client.post(f"/api/v1/chats/{chat_id}/clear", headers=HEADERS).status_code == 200

    assert messages(client, chat_id) == [] and private_files(client) == []
    assert db(client, "SELECT COUNT(*) FROM message_attachments") == [(0,)]


def test_removing_a_library_file_that_is_attached_keeps_it_for_the_chat(client, tmp_path):
    file = chat_upload(client, user_pdf(tmp_path), save_to_library=True)["file"]
    chat_id = new_chat(client)
    send(client, chat_id, "attached", [file["id"]])

    removed = client.delete(f"/api/v1/library/uploads/{file['id']}", headers=HEADERS)

    assert removed.status_code == 204 and library_listing(client) == []
    assert len(private_files(client)) == 1 and len(messages(client, chat_id)[0]["attachments"]) == 1
    client.delete(f"/api/v1/chats/{chat_id}", headers=HEADERS)  # now nothing references it
    assert private_files(client) == [] and db(client, "SELECT COUNT(*) FROM library_files") == [(0,)]


def test_the_database_refuses_to_delete_a_file_that_messages_still_reference(client, tmp_path):
    file = chat_upload(client, user_pdf(tmp_path))["file"]
    send(client, new_chat(client), "x", [file["id"]])

    connection = sqlite3.connect(client.data_dir / "studybot.db")
    connection.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM library_files WHERE id = ?", (file["id"],))
    connection.close()


def test_startup_removes_old_unsent_chat_uploads_only(tmp_path):
    original = user_pdf(tmp_path)
    with make_client(tmp_path, SpyExtractor()) as client:
        client.data_dir = tmp_path
        unsent = chat_upload(client, original)["file"]["id"]
        recent = chat_upload(client, user_pdf(tmp_path, "recent.pdf", pages=("recent",)))["file"]["id"]
        sent = chat_upload(client, user_pdf(tmp_path, "sent.pdf", pages=("sent",)))["file"]["id"]
        library = chat_upload(client, user_pdf(tmp_path, "lib.pdf", pages=("lib",)), save_to_library=True)["file"]["id"]
        send(client, new_chat(client), "sent", [sent])
    old = (time.time() - 3 * 24 * 3600)
    from datetime import datetime, timezone

    stamp = datetime.fromtimestamp(old, timezone.utc).isoformat()
    connection = sqlite3.connect(tmp_path / "studybot.db")
    connection.execute(
        "UPDATE library_files SET updated_at = ? WHERE id IN (?, ?, ?)", (stamp, unsent, sent, library)
    )
    connection.commit()
    connection.close()

    with make_client(tmp_path, SpyExtractor()) as client:
        client.data_dir = tmp_path
        ids = {r[0] for r in db(client, "SELECT id FROM library_files")}

    assert ids == {recent, sent, library}  # only the old, unsent, unreferenced chat upload is gone
    assert len(private_files(client)) == 3


# --- privacy and auth ----------------------------------------------------------------


def test_nothing_private_leaks_through_attachment_dtos(client, tmp_path):
    file = chat_upload(client, user_pdf(tmp_path, pages=("CONFIDENTIAL TEXT", "more")))["file"]
    chat_id = new_chat(client)
    send(client, chat_id, "check", [file["id"]])
    listing = client.get(f"/api/v1/chats/{chat_id}/messages", headers=HEADERS)
    [stored] = private_files(client)

    assert "CONFIDENTIAL" not in listing.text and stored not in listing.text and str(client.data_dir) not in listing.text


def test_the_discard_endpoint_requires_the_token(client):
    assert client.delete("/api/v1/library/attachments/x").status_code == 401
