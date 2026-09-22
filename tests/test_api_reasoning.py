import pytest
from fastapi.testclient import TestClient

from studybot.api.server import create_app
from studybot.config.settings import Settings

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path):
    settings = Settings.from_env(
        env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)}
    )
    app = create_app(settings=settings, token=TOKEN)
    with TestClient(app) as c:
        yield c


def send(client, chat_id, content):
    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "send_message", "chat_id": chat_id, "content": content})
        while True:
            event = ws.receive_json()
            if event["type"] == "message_completed":
                return
            if event["type"] == "error":
                raise AssertionError(f"unexpected error event: {event}")


def test_list_reasoning_modes_catalog(client):
    response = client.get("/api/v1/reasoning-modes", headers=HEADERS)

    assert response.status_code == 200
    ids = {m["id"] for m in response.json()}
    assert ids == {"fast", "deep"}
    for mode in response.json():
        assert mode["displayName"]
        assert mode["description"]


def test_reasoning_modes_catalog_requires_auth(client):
    response = client.get("/api/v1/reasoning-modes")

    assert response.status_code == 401


def test_new_chat_defaults_to_fast_reasoning_mode(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()

    assert chat["reasoningMode"] == "fast"


def test_get_current_chat_reasoning_mode_defaults_to_fast(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()

    response = client.get(f"/api/v1/chats/{chat['id']}/reasoning-mode", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["id"] == "fast"
    assert response.json()["displayName"] == "Fast"


def test_change_chat_reasoning_mode(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()

    response = client.put(
        f"/api/v1/chats/{chat['id']}/reasoning-mode", json={"reasoningMode": "deep"}, headers=HEADERS
    )

    assert response.status_code == 200
    assert response.json()["id"] == "deep"
    assert response.json()["displayName"] == "Deep Think"


def test_reasoning_mode_change_persists(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, chat["id"], "hello")  # force persistence
    client.put(f"/api/v1/chats/{chat['id']}/reasoning-mode", json={"reasoningMode": "deep"}, headers=HEADERS)

    response = client.get(f"/api/v1/chats/{chat['id']}", headers=HEADERS)

    assert response.json()["reasoningMode"] == "deep"


def test_reasoning_mode_change_does_not_affect_teaching_mode(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, chat["id"], "hello")  # force persistence — GET /chats/{id} below is stateless
    client.put(f"/api/v1/chats/{chat['id']}/mode", json={"mode": "homework"}, headers=HEADERS)

    client.put(f"/api/v1/chats/{chat['id']}/reasoning-mode", json={"reasoningMode": "deep"}, headers=HEADERS)

    response = client.get(f"/api/v1/chats/{chat['id']}", headers=HEADERS)
    assert response.json()["teachingMode"] == "homework"
    assert response.json()["reasoningMode"] == "deep"


def test_invalid_reasoning_mode_is_rejected(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()

    response = client.put(
        f"/api/v1/chats/{chat['id']}/reasoning-mode",
        json={"reasoningMode": "not-a-real-mode"},
        headers=HEADERS,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REASONING_MODE"


def test_reasoning_mode_change_on_unknown_chat_is_not_found(client):
    response = client.put(
        "/api/v1/chats/does-not-exist/reasoning-mode", json={"reasoningMode": "fast"}, headers=HEADERS
    )

    assert response.status_code == 404
    assert response.json()["code"] == "CHAT_NOT_FOUND"


def test_different_chats_have_independent_reasoning_modes(client):
    # Per API_CONTRACT.md's "Lazy persistence": a chat isn't retrievable by
    # a *different* request path (switching the active chat via
    # PUT .../reasoning-mode below) until it has a database row, which only
    # its first message creates.
    chat_a = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, chat_a["id"], "hello")
    chat_b = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, chat_b["id"], "hello")

    client.put(f"/api/v1/chats/{chat_a['id']}/reasoning-mode", json={"reasoningMode": "deep"}, headers=HEADERS)

    a = client.get(f"/api/v1/chats/{chat_a['id']}/reasoning-mode", headers=HEADERS).json()
    b = client.get(f"/api/v1/chats/{chat_b['id']}/reasoning-mode", headers=HEADERS).json()
    assert a["id"] == "deep"
    assert b["id"] == "fast"
