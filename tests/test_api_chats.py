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
                return event
            if event["type"] == "error":
                raise AssertionError(f"unexpected error event: {event}")


def test_create_chat_defaults_to_general_and_teach_mode(client):
    response = client.post("/api/v1/chats", json={}, headers=HEADERS)

    assert response.status_code == 201
    body = response.json()
    assert body["courseId"] is None
    assert body["teachingMode"] == "teach"


def test_create_chat_with_course(client):
    course = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()

    response = client.post("/api/v1/chats", json={"courseId": course["id"]}, headers=HEADERS)

    assert response.status_code == 201
    assert response.json()["courseId"] == course["id"]


def test_create_chat_with_unknown_course_is_rejected(client):
    response = client.post("/api/v1/chats", json={"courseId": "does-not-exist"}, headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["code"] == "COURSE_NOT_FOUND"


def test_get_chat_found_immediately_after_creation(client):
    # Stage 5.8: an API-created chat is a real, persisted row from the
    # moment POST returns — it must never need a first message (or any
    # other "activation") to become addressable. See API_CONTRACT.md.
    created = client.post("/api/v1/chats", json={}, headers=HEADERS).json()

    response = client.get(f"/api/v1/chats/{created['id']}", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_list_chats_all(client):
    chat_a = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, chat_a["id"], "hello a")
    chat_b = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, chat_b["id"], "hello b")

    response = client.get("/api/v1/chats", headers=HEADERS)

    assert response.status_code == 200
    ids = {c["id"] for c in response.json()}
    assert {chat_a["id"], chat_b["id"]} <= ids


def test_list_chats_filtered_by_course(client):
    course = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()
    in_course = client.post("/api/v1/chats", json={"courseId": course["id"]}, headers=HEADERS).json()
    send(client, in_course["id"], "in course")
    general = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, general["id"], "general")

    response = client.get("/api/v1/chats", params={"course_id": course["id"]}, headers=HEADERS)
    assert [c["id"] for c in response.json()] == [in_course["id"]]

    response = client.get("/api/v1/chats", params={"course_id": "none"}, headers=HEADERS)
    assert [c["id"] for c in response.json()] == [general["id"]]


def test_get_chat_history(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, chat["id"], "hello")

    response = client.get(f"/api/v1/chats/{chat['id']}/messages", headers=HEADERS)

    assert response.status_code == 200
    messages = response.json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "hello"
    assert all("id" in m and "createdAt" in m for m in messages)


def test_get_history_not_found(client):
    response = client.get("/api/v1/chats/does-not-exist/messages", headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["code"] == "CHAT_NOT_FOUND"


def test_rename_chat(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, chat["id"], "hello")

    response = client.put(f"/api/v1/chats/{chat['id']}/rename", json={"title": "My Chat"}, headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["title"] == "My Chat"


def test_rename_chat_not_found(client):
    response = client.put("/api/v1/chats/does-not-exist/rename", json={"title": "X"}, headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["code"] == "CHAT_NOT_FOUND"


def test_rename_chat_rejects_empty_title(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, chat["id"], "hello")

    response = client.put(f"/api/v1/chats/{chat['id']}/rename", json={"title": "   "}, headers=HEADERS)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_clear_chat_removes_messages_but_keeps_chat(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, chat["id"], "hello")

    response = client.post(f"/api/v1/chats/{chat['id']}/clear", headers=HEADERS)

    assert response.status_code == 200
    messages = client.get(f"/api/v1/chats/{chat['id']}/messages", headers=HEADERS).json()
    assert messages == []
    assert client.get(f"/api/v1/chats/{chat['id']}", headers=HEADERS).status_code == 200


def test_delete_chat(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, chat["id"], "hello")

    response = client.delete(f"/api/v1/chats/{chat['id']}", headers=HEADERS)

    assert response.status_code == 204
    assert client.get(f"/api/v1/chats/{chat['id']}", headers=HEADERS).status_code == 404


def test_delete_chat_not_found(client):
    response = client.delete("/api/v1/chats/does-not-exist", headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["code"] == "CHAT_NOT_FOUND"


def test_assign_chat_to_course(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, chat["id"], "hello")
    course = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()

    response = client.put(
        f"/api/v1/chats/{chat['id']}/course", json={"courseId": course["id"]}, headers=HEADERS
    )

    assert response.status_code == 200
    assert response.json()["courseId"] == course["id"]


def test_unassign_chat_from_course(client):
    course = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()
    chat = client.post("/api/v1/chats", json={"courseId": course["id"]}, headers=HEADERS).json()
    send(client, chat["id"], "hello")

    response = client.put(f"/api/v1/chats/{chat['id']}/course", json={"courseId": None}, headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["courseId"] is None


def test_assign_chat_to_unknown_course(client):
    chat = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    send(client, chat["id"], "hello")

    response = client.put(
        f"/api/v1/chats/{chat['id']}/course", json={"courseId": "does-not-exist"}, headers=HEADERS
    )

    assert response.status_code == 404
    assert response.json()["code"] == "COURSE_NOT_FOUND"


# --- Stage 5.8: stateless multi-chat regressions --------------------------------------


def test_creating_chat_b_does_not_break_addressing_chat_a(client):
    """The exact real bug this stage fixes, at the HTTP layer: create A, do
    NOT message it, create B, then operate on A by id — must not 404."""
    chat_a = client.post("/api/v1/chats", json={}, headers=HEADERS).json()
    client.post("/api/v1/chats", json={}, headers=HEADERS)  # chat B, never touched again

    response = client.get(f"/api/v1/chats/{chat_a['id']}", headers=HEADERS)
    assert response.status_code == 200

    response = client.put(f"/api/v1/chats/{chat_a['id']}/rename", json={"title": "A"}, headers=HEADERS)
    assert response.status_code == 200


def test_restart_both_chats_remain_independently_addressable(tmp_path):
    env = {"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)}

    with TestClient(create_app(settings=Settings.from_env(env=env), token=TOKEN)) as client1:
        chat_a = client1.post("/api/v1/chats", json={}, headers=HEADERS).json()
        chat_b = client1.post("/api/v1/chats", json={}, headers=HEADERS).json()
        send(client1, chat_a["id"], "hello a")
        client1.put(f"/api/v1/chats/{chat_b['id']}/reasoning-mode", json={"reasoningMode": "deep"}, headers=HEADERS)
        send(client1, chat_b["id"], "hello b")

    # A brand-new app/engine, same on-disk database — simulates a server restart.
    with TestClient(create_app(settings=Settings.from_env(env=env), token=TOKEN)) as client2:
        response_a = client2.get(f"/api/v1/chats/{chat_a['id']}", headers=HEADERS)
        response_b = client2.get(f"/api/v1/chats/{chat_b['id']}", headers=HEADERS)

        assert response_a.status_code == 200
        assert response_b.status_code == 200
        assert response_b.json()["reasoningMode"] == "deep"

        messages_a = client2.get(f"/api/v1/chats/{chat_a['id']}/messages", headers=HEADERS).json()
        messages_b = client2.get(f"/api/v1/chats/{chat_b['id']}/messages", headers=HEADERS).json()
        assert [m["content"] for m in messages_a] == ["hello a", "[Mock] You said: hello a"]
        assert [m["content"] for m in messages_b] == ["hello b", "[Mock] You said: hello b"]
