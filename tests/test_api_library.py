import base64
import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

from studybot.api.server import create_app
from studybot.config.settings import Settings

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
BOOKMARK = b"\x00bookmark-bytes\xff" * 8
ENCODED = base64.b64encode(BOOKMARK).decode()


@pytest.fixture
def client(tmp_path):
    settings = Settings.from_env(env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)})
    with TestClient(create_app(settings=settings, token=TOKEN)) as c:
        c.data_dir = tmp_path
        yield c


def authorization(payload=ENCODED, platform="macos", kind="security_scoped_bookmark"):
    return {"platform": platform, "kind": kind, "payload": payload}


def create(client, locator="/library/PHY215", name="PHY215", **auth):
    return client.post(
        "/api/v1/library/sources/local-folder",
        json={"displayName": name, "locator": locator, "authorization": authorization(**auth)},
        headers=HEADERS,
    )


# --- authentication ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/library/sources"),
        ("post", "/api/v1/library/sources/local-folder"),
        ("delete", "/api/v1/library/sources/x"),
        ("get", "/api/v1/library/sources/x/authorization"),
        ("put", "/api/v1/library/sources/x/authorization"),
    ],
)
def test_library_endpoints_require_the_token(client, method, path):
    response = getattr(client, method)(path)

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_empty_library(client):
    response = client.get("/api/v1/library/sources", headers=HEADERS)

    assert response.status_code == 200 and response.json() == []


# --- create / list -------------------------------------------------------------------


def test_create_source_with_authorization(client):
    response = create(client)

    assert response.status_code == 201
    body = response.json()
    assert body["displayName"] == "PHY215" and body["kind"] == "local_folder"
    assert body["courseId"] is None and body["hasAuthorization"] is True
    assert set(body) == {"id", "courseId", "kind", "displayName", "locator", "createdAt", "updatedAt", "hasAuthorization"}


def test_list_never_contains_the_authorization_payload(client):
    create(client)

    response = client.get("/api/v1/library/sources", headers=HEADERS)

    [source] = response.json()
    assert source["hasAuthorization"] is True
    assert ENCODED not in response.text and "payload" not in response.text


def test_get_authorization_returns_the_stored_payload(client):
    source_id = create(client).json()["id"]

    response = client.get(f"/api/v1/library/sources/{source_id}/authorization", headers=HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "sourceId": source_id, "platform": "macos", "kind": "security_scoped_bookmark", "payload": ENCODED,
    }


def test_duplicate_selection_reuses_the_source_and_replaces_the_authorization(client):
    first = create(client, locator="/library/PHY215/").json()
    newer = base64.b64encode(b"refreshed").decode()

    second = create(client, locator="/library//PHY215", name="Other name", payload=newer)

    assert second.status_code == 200
    assert second.json()["id"] == first["id"] and second.json()["displayName"] == "PHY215"
    assert len(client.get("/api/v1/library/sources", headers=HEADERS).json()) == 1
    stored = client.get(f"/api/v1/library/sources/{first['id']}/authorization", headers=HEADERS).json()
    assert stored["payload"] == newer


def test_replace_authorization(client):
    source_id = create(client).json()["id"]
    newer = base64.b64encode(b"new bookmark").decode()

    response = client.put(
        f"/api/v1/library/sources/{source_id}/authorization", json=authorization(payload=newer), headers=HEADERS
    )

    assert response.status_code == 200 and response.json()["id"] == source_id
    assert client.get(f"/api/v1/library/sources/{source_id}/authorization", headers=HEADERS).json()["payload"] == newer


def test_unknown_source_errors(client):
    for response in (
        client.get("/api/v1/library/sources/nope/authorization", headers=HEADERS),
        client.put("/api/v1/library/sources/nope/authorization", json=authorization(), headers=HEADERS),
        client.delete("/api/v1/library/sources/nope", headers=HEADERS),
    ):
        assert response.status_code == 404
        assert response.json()["code"] == "LIBRARY_SOURCE_NOT_FOUND"


def test_source_without_authorization_reports_it(client):
    create(client)
    # A source created before authorization existed (e.g. migrated from v6) has none.
    connection = sqlite3.connect(client.data_dir / "studybot.db")
    connection.execute("DELETE FROM library_source_authorizations")
    connection.commit()
    connection.close()

    [source] = client.get("/api/v1/library/sources", headers=HEADERS).json()
    response = client.get(f"/api/v1/library/sources/{source['id']}/authorization", headers=HEADERS)

    assert source["hasAuthorization"] is False
    assert response.status_code == 404 and response.json()["code"] == "LIBRARY_AUTHORIZATION_NOT_FOUND"


def test_delete_source_removes_its_authorization_only_in_the_database(client, tmp_path):
    real_folder = tmp_path / "real-folder"
    real_folder.mkdir()
    (real_folder / "note.txt").write_text("keep")
    source_id = create(client, locator=str(real_folder)).json()["id"]

    response = client.delete(f"/api/v1/library/sources/{source_id}", headers=HEADERS)

    assert response.status_code == 204
    assert client.get("/api/v1/library/sources", headers=HEADERS).json() == []
    connection = sqlite3.connect(client.data_dir / "studybot.db")
    assert connection.execute("SELECT COUNT(*) FROM library_source_authorizations").fetchone()[0] == 0
    connection.close()
    assert (real_folder / "note.txt").read_text() == "keep"


# --- validation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "auth",
    [
        {"payload": ""},
        {"payload": "not base64 !!!"},
        {"payload": base64.b64encode(b"x" * (1024 * 1024 + 1)).decode()},
        {"platform": "windows"},
        {"kind": "password"},
    ],
)
def test_malformed_authorization_is_rejected_cleanly(client, auth):
    response = create(client, **auth)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert client.get("/api/v1/library/sources", headers=HEADERS).json() == []  # nothing half-created


def test_validation_errors_never_echo_the_payload(client):
    secret = "SECRET-PAYLOAD-VALUE"

    wrong_shape = client.post(
        "/api/v1/library/sources/local-folder",
        json={"displayName": "x", "locator": "/x", "authorization": {"platform": "macos", "kind": "k", "payload": [secret]}},
        headers=HEADERS,
    )
    bad_base64 = create(client, payload=secret + "!")

    for response in (wrong_shape, bad_base64):
        assert response.status_code == 422
        assert secret not in response.text


def test_replace_with_bad_payload_keeps_the_previous_authorization(client):
    source_id = create(client).json()["id"]

    response = client.put(
        f"/api/v1/library/sources/{source_id}/authorization", json=authorization(payload=""), headers=HEADERS
    )

    assert response.status_code == 422
    assert client.get(f"/api/v1/library/sources/{source_id}/authorization", headers=HEADERS).json()["payload"] == ENCODED


def test_authorization_is_never_logged(client, caplog):
    caplog.set_level(logging.DEBUG)

    create(client)
    create(client, payload="!!bad!!")
    client.get("/api/v1/library/sources", headers=HEADERS)

    assert ENCODED not in caplog.text
    assert base64.b64encode(BOOKMARK).decode() not in caplog.text
    assert "/library/PHY215" not in caplog.text
