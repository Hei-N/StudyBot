import logging

import pytest
from fastapi.testclient import TestClient

from studybot.api.server import create_app
from studybot.config.settings import Settings

TOKEN = "test-secret-token-value"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path):
    settings = Settings.from_env(
        env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)}
    )
    app = create_app(settings=settings, token=TOKEN)
    with TestClient(app) as c:
        yield c


def test_planted_user_secret_absent_from_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    secret = "WATERMELON_SECRET_998"
    chat_id = client.post("/api/v1/chats", json={}, headers=HEADERS).json()["id"]

    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "send_message", "chat_id": chat_id, "content": f"my secret is {secret}"})
        while ws.receive_json()["type"] != "message_completed":
            pass

    assert secret not in caplog.text


def test_planted_course_description_absent_from_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    secret = "PINEAPPLE_COURSE_SECRET_442"

    client.post(
        "/api/v1/courses",
        json={"name": "Secret Course", "description": f"This has {secret} in it"},
        headers=HEADERS,
    )

    assert secret not in caplog.text


def test_auth_token_absent_from_logs_across_many_requests(client, caplog):
    caplog.set_level(logging.DEBUG)

    client.get("/api/v1/health", headers=HEADERS)
    client.get("/api/v1/courses", headers=HEADERS)
    client.post("/api/v1/chats", json={}, headers=HEADERS)
    client.get("/api/v1/health", headers={"Authorization": "Bearer some-wrong-token"})

    assert TOKEN not in caplog.text
    assert "some-wrong-token" not in caplog.text


def test_rename_content_absent_from_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    secret = "BANANA_TITLE_SECRET_77"
    chat_id = client.post("/api/v1/chats", json={}, headers=HEADERS).json()["id"]
    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "send_message", "chat_id": chat_id, "content": "hello"})
        while ws.receive_json()["type"] != "message_completed":
            pass

    client.put(f"/api/v1/chats/{chat_id}/rename", json={"title": secret}, headers=HEADERS)

    assert secret not in caplog.text


def test_learning_memory_topic_and_summary_absent_from_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    topic_secret = "MANGO_TOPIC_SECRET_51"
    summary_secret = "KIWI_SUMMARY_SECRET_62"

    memory = client.post(
        "/api/v1/memories",
        json={"topic": topic_secret, "kind": "needs_review", "summary": summary_secret},
        headers=HEADERS,
    ).json()
    client.patch(f"/api/v1/memories/{memory['id']}", json={"summary": "updated " + summary_secret}, headers=HEADERS)
    client.post(f"/api/v1/memories/{memory['id']}/archive", headers=HEADERS)
    client.post(f"/api/v1/memories/{memory['id']}/restore", headers=HEADERS)

    assert topic_secret not in caplog.text
    assert summary_secret not in caplog.text


def test_learning_memory_context_absent_from_logs_when_injected_into_a_chat(client, caplog):
    """The memory context text (built for the model, never for a log) must
    not appear in logs even when a chat actually uses it."""
    caplog.set_level(logging.DEBUG)
    secret = "PAPAYA_MEMORY_CONTEXT_SECRET_73"
    course = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()
    client.post(
        "/api/v1/memories",
        json={"topic": "Vectors", "kind": "needs_review", "summary": secret, "courseId": course["id"]},
        headers=HEADERS,
    )
    chat_id = client.post("/api/v1/chats", json={"courseId": course["id"]}, headers=HEADERS).json()["id"]

    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "send_message", "chat_id": chat_id, "content": "hello"})
        while ws.receive_json()["type"] != "message_completed":
            pass

    assert secret not in caplog.text
