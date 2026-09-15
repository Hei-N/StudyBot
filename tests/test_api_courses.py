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


def test_list_courses_empty_initially(client):
    response = client.get("/api/v1/courses", headers=HEADERS)

    assert response.status_code == 200
    assert response.json() == []


def test_create_course(client):
    response = client.post(
        "/api/v1/courses",
        json={"name": "University Physics I", "code": "PHY 215", "term": "Fall 2026", "description": "Mechanics"},
        headers=HEADERS,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "University Physics I"
    assert body["code"] == "PHY 215"
    assert body["term"] == "Fall 2026"
    assert body["description"] == "Mechanics"
    assert "id" in body and body["id"]
    assert "createdAt" in body
    assert "updatedAt" in body


def test_create_course_with_only_name(client):
    response = client.post("/api/v1/courses", json={"name": "Calculus III"}, headers=HEADERS)

    assert response.status_code == 201
    body = response.json()
    assert body["code"] is None
    assert body["term"] is None
    assert body["description"] is None


def test_create_course_rejects_empty_name(client):
    response = client.post("/api/v1/courses", json={"name": "   "}, headers=HEADERS)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_list_courses_reflects_created_courses(client):
    client.post("/api/v1/courses", json={"name": "A"}, headers=HEADERS)
    client.post("/api/v1/courses", json={"name": "B"}, headers=HEADERS)

    response = client.get("/api/v1/courses", headers=HEADERS)

    assert response.status_code == 200
    assert {c["name"] for c in response.json()} == {"A", "B"}


def test_get_course_by_id(client):
    created = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()

    response = client.get(f"/api/v1/courses/{created['id']}", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_course_not_found(client):
    response = client.get("/api/v1/courses/does-not-exist", headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["code"] == "COURSE_NOT_FOUND"


def test_update_course_replaces_fields(client):
    created = client.post(
        "/api/v1/courses", json={"name": "Old", "code": "OLD"}, headers=HEADERS
    ).json()

    response = client.put(
        f"/api/v1/courses/{created['id']}",
        json={"name": "New", "code": "NEW", "term": "Fall", "description": "desc"},
        headers=HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "New"
    assert body["code"] == "NEW"
    assert body["term"] == "Fall"
    assert body["description"] == "desc"


def test_update_course_not_found(client):
    response = client.put(
        "/api/v1/courses/does-not-exist", json={"name": "New"}, headers=HEADERS
    )

    assert response.status_code == 404
    assert response.json()["code"] == "COURSE_NOT_FOUND"


def test_update_course_rejects_empty_name(client):
    created = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()

    response = client.put(f"/api/v1/courses/{created['id']}", json={"name": "  "}, headers=HEADERS)

    assert response.status_code == 422


def test_delete_course_removes_it(client):
    created = client.post("/api/v1/courses", json={"name": "Doomed"}, headers=HEADERS).json()

    response = client.delete(f"/api/v1/courses/{created['id']}", headers=HEADERS)

    assert response.status_code == 204
    assert client.get(f"/api/v1/courses/{created['id']}", headers=HEADERS).status_code == 404


def test_delete_course_not_found(client):
    response = client.delete("/api/v1/courses/does-not-exist", headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["code"] == "COURSE_NOT_FOUND"


def test_deleting_course_preserves_chats_and_messages_as_general(client):
    course = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()
    chat = client.post("/api/v1/chats", json={"courseId": course["id"]}, headers=HEADERS).json()

    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "send_message", "chat_id": chat["id"], "content": "hello"})
        while ws.receive_json()["type"] != "message_completed":
            pass

    response = client.delete(f"/api/v1/courses/{course['id']}", headers=HEADERS)
    assert response.status_code == 204

    chat_after = client.get(f"/api/v1/chats/{chat['id']}", headers=HEADERS).json()
    assert chat_after["courseId"] is None

    messages = client.get(f"/api/v1/chats/{chat['id']}/messages", headers=HEADERS).json()
    assert len(messages) == 2


def test_unicode_and_burmese_course_names(client):
    for name in ["大学物理", "ရူပဗေဒ", "Physics ⚛️"]:
        response = client.post("/api/v1/courses", json={"name": name}, headers=HEADERS)
        assert response.status_code == 201
        assert response.json()["name"] == name


def test_multiline_description_round_trips(client):
    description = "Line one\nLine two\n\nLine four"
    response = client.post(
        "/api/v1/courses", json={"name": "Title", "description": description}, headers=HEADERS
    )

    assert response.json()["description"] == description
