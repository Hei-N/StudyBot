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


def test_list_modes_catalog(client):
    response = client.get("/api/v1/modes", headers=HEADERS)

    assert response.status_code == 200
    ids = {m["id"] for m in response.json()}
    assert ids == {"teach", "homework", "quick", "practice", "exam"}
    for mode in response.json():
        assert mode["displayName"]
        assert mode["description"]


def test_get_current_chat_mode_defaults_to_teach(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()

    response = client.get(f"/api/v1/chats/{chat['id']}/mode", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["id"] == "teach"


def test_change_chat_mode(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()

    response = client.put(f"/api/v1/chats/{chat['id']}/mode", json={"mode": "homework"}, headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["id"] == "homework"
    assert response.json()["displayName"] == "Homework"


def test_mode_change_persists(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, chat["id"], "hello")  # force persistence
    client.put(f"/api/v1/chats/{chat['id']}/mode", json={"mode": "exam"}, headers=HEADERS)

    response = client.get(f"/api/v1/chats/{chat['id']}", headers=HEADERS)

    assert response.json()["teachingMode"] == "exam"


def test_invalid_mode_is_rejected(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()

    response = client.put(
        f"/api/v1/chats/{chat['id']}/mode", json={"mode": "not-a-real-mode"}, headers=HEADERS
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_MODE"


def test_mode_change_on_unknown_chat_is_not_found(client):
    response = client.put(
        "/api/v1/chats/does-not-exist/mode", json={"mode": "teach"}, headers=HEADERS
    )

    assert response.status_code == 404
    assert response.json()["code"] == "CHAT_NOT_FOUND"
