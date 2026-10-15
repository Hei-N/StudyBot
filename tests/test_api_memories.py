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


def create_memory(client, **overrides):
    body = {"topic": "Vector components", "kind": "needs_review", "summary": "Mixes x/y components."}
    body.update(overrides)
    return client.post("/api/v1/memories", json=body, headers=HEADERS)


# --- catalog -----------------------------------------------------------------------------


def test_memory_kinds_catalog_lists_all_five(client):
    response = client.get("/api/v1/memory-kinds", headers=HEADERS)

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert ids == {"understands", "needs_review", "misconception", "learning_goal", "useful_strategy"}
    for item in response.json():
        assert item["displayName"]
        assert item["description"]


def test_memory_kinds_requires_auth(client):
    response = client.get("/api/v1/memory-kinds")
    assert response.status_code == 401


# --- create / get --------------------------------------------------------------------------


def test_create_memory(client):
    response = create_memory(client)

    assert response.status_code == 201
    body = response.json()
    assert body["topic"] == "Vector components"
    assert body["kind"] == "needs_review"
    assert body["status"] == "active"
    assert body["courseId"] is None
    assert body["sourceChatId"] is None
    assert "id" in body and "createdAt" in body and "updatedAt" in body


def test_create_memory_requires_auth(client):
    response = client.post(
        "/api/v1/memories",
        json={"topic": "T", "kind": "needs_review", "summary": "S"},
    )
    assert response.status_code == 401


def test_create_memory_with_course_and_chat(client):
    course = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()
    chat = client.post("/api/v1/chats", json={"courseId": course["id"]}, headers=HEADERS).json()

    response = create_memory(client, courseId=course["id"], sourceChatId=chat["id"])

    assert response.status_code == 201
    body = response.json()
    assert body["courseId"] == course["id"]
    assert body["sourceChatId"] == chat["id"]


def test_create_memory_with_unknown_course_is_rejected(client):
    response = create_memory(client, courseId="does-not-exist")

    assert response.status_code == 404
    assert response.json()["code"] == "COURSE_NOT_FOUND"


def test_create_memory_with_unknown_chat_is_rejected(client):
    response = create_memory(client, sourceChatId="does-not-exist")

    assert response.status_code == 404
    assert response.json()["code"] == "CHAT_NOT_FOUND"


def test_create_memory_with_unknown_kind_is_rejected(client):
    response = create_memory(client, kind="mastery_percentage")

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_MEMORY_KIND"


def test_create_memory_rejects_empty_topic(client):
    response = create_memory(client, topic="   ")

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_create_memory_rejects_empty_summary(client):
    response = create_memory(client, summary="   ")

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_create_duplicate_memory_is_rejected(client):
    create_memory(client)

    response = create_memory(client)

    assert response.status_code == 409
    assert response.json()["code"] == "MEMORY_CONFLICT"


def test_create_memory_supports_unicode_burmese_and_emoji(client):
    response = create_memory(
        client,
        topic="Newton's Laws ⚙️",
        summary="student confuses အရှိန် (acceleration) with velocity; also struggles with 二次函数",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["topic"] == "Newton's Laws ⚙️"
    assert "အရှိန်" in body["summary"]
    assert "二次函数" in body["summary"]


def test_get_memory(client):
    created = create_memory(client).json()

    response = client.get(f"/api/v1/memories/{created['id']}", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_memory_not_found(client):
    response = client.get("/api/v1/memories/does-not-exist", headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["code"] == "MEMORY_NOT_FOUND"


# --- list / filters --------------------------------------------------------------------


def test_list_memories_all(client):
    create_memory(client, topic="A")
    create_memory(client, topic="B")

    response = client.get("/api/v1/memories", headers=HEADERS)

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_memories_filtered_by_course(client):
    course = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()
    create_memory(client, topic="In course", courseId=course["id"])
    create_memory(client, topic="Global")

    response = client.get("/api/v1/memories", params={"course_id": course["id"]}, headers=HEADERS)
    assert [m["topic"] for m in response.json()] == ["In course"]

    response = client.get("/api/v1/memories", params={"course_id": "none"}, headers=HEADERS)
    assert [m["topic"] for m in response.json()] == ["Global"]


def test_list_memories_filtered_by_kind(client):
    create_memory(client, topic="A", kind="needs_review")
    create_memory(client, topic="B", kind="understands")

    response = client.get("/api/v1/memories", params={"kind": "understands"}, headers=HEADERS)
    assert [m["topic"] for m in response.json()] == ["B"]


def test_list_memories_filtered_by_status(client):
    memory = create_memory(client, topic="A").json()
    create_memory(client, topic="B")
    client.post(f"/api/v1/memories/{memory['id']}/archive", headers=HEADERS)

    active = client.get("/api/v1/memories", params={"status": "active"}, headers=HEADERS).json()
    archived = client.get("/api/v1/memories", params={"status": "archived"}, headers=HEADERS).json()
    assert [m["topic"] for m in active] == ["B"]
    assert [m["topic"] for m in archived] == ["A"]


def test_list_memories_unknown_kind_filter_is_rejected(client):
    response = client.get("/api/v1/memories", params={"kind": "bogus"}, headers=HEADERS)

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_MEMORY_KIND"


def test_list_memories_unknown_status_filter_is_rejected(client):
    response = client.get("/api/v1/memories", params={"status": "bogus"}, headers=HEADERS)

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_MEMORY_STATUS"


# --- update (PATCH) ----------------------------------------------------------------------


def test_patch_updates_topic(client):
    memory = create_memory(client).json()

    response = client.patch(f"/api/v1/memories/{memory['id']}", json={"topic": "New topic"}, headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["topic"] == "New topic"
    assert body["summary"] == "Mixes x/y components."  # unchanged


def test_patch_updates_kind(client):
    memory = create_memory(client).json()

    response = client.patch(f"/api/v1/memories/{memory['id']}", json={"kind": "understands"}, headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["kind"] == "understands"


def test_patch_updates_summary(client):
    memory = create_memory(client).json()

    response = client.patch(
        f"/api/v1/memories/{memory['id']}", json={"summary": "Now understands components."}, headers=HEADERS
    )

    assert response.status_code == 200
    assert response.json()["summary"] == "Now understands components."


def test_patch_omitting_course_id_leaves_it_unchanged(client):
    course = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()
    memory = create_memory(client, courseId=course["id"]).json()

    response = client.patch(f"/api/v1/memories/{memory['id']}", json={"topic": "New"}, headers=HEADERS)

    assert response.json()["courseId"] == course["id"]


def test_patch_explicit_null_course_id_unassigns(client):
    course = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()
    memory = create_memory(client, courseId=course["id"]).json()

    response = client.patch(f"/api/v1/memories/{memory['id']}", json={"courseId": None}, headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["courseId"] is None


def test_patch_to_a_real_course_id(client):
    course = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()
    memory = create_memory(client).json()

    response = client.patch(f"/api/v1/memories/{memory['id']}", json={"courseId": course["id"]}, headers=HEADERS)

    assert response.json()["courseId"] == course["id"]


def test_patch_not_found(client):
    response = client.patch("/api/v1/memories/does-not-exist", json={"topic": "X"}, headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["code"] == "MEMORY_NOT_FOUND"


def test_patch_into_duplicate_is_rejected(client):
    create_memory(client, topic="Vectors")
    other = create_memory(client, topic="Displacement").json()

    response = client.patch(f"/api/v1/memories/{other['id']}", json={"topic": "Vectors"}, headers=HEADERS)

    assert response.status_code == 409
    assert response.json()["code"] == "MEMORY_CONFLICT"


def test_patch_rejects_empty_topic(client):
    memory = create_memory(client).json()

    response = client.patch(f"/api/v1/memories/{memory['id']}", json={"topic": "   "}, headers=HEADERS)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_patch_unknown_kind_is_rejected(client):
    memory = create_memory(client).json()

    response = client.patch(f"/api/v1/memories/{memory['id']}", json={"kind": "bogus"}, headers=HEADERS)

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_MEMORY_KIND"


# --- archive / restore ------------------------------------------------------------------


def test_archive_memory(client):
    memory = create_memory(client).json()

    response = client.post(f"/api/v1/memories/{memory['id']}/archive", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "archived"


def test_archive_not_found(client):
    response = client.post("/api/v1/memories/does-not-exist/archive", headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["code"] == "MEMORY_NOT_FOUND"


def test_restore_memory(client):
    memory = create_memory(client).json()
    client.post(f"/api/v1/memories/{memory['id']}/archive", headers=HEADERS)

    response = client.post(f"/api/v1/memories/{memory['id']}/restore", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_restore_not_found(client):
    response = client.post("/api/v1/memories/does-not-exist/restore", headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["code"] == "MEMORY_NOT_FOUND"


def test_restore_into_conflict_is_rejected(client):
    memory = create_memory(client, topic="Vectors").json()
    client.post(f"/api/v1/memories/{memory['id']}/archive", headers=HEADERS)
    create_memory(client, topic="Vectors")  # now the active one

    response = client.post(f"/api/v1/memories/{memory['id']}/restore", headers=HEADERS)

    assert response.status_code == 409
    assert response.json()["code"] == "MEMORY_CONFLICT"


# --- delete ------------------------------------------------------------------------------


def test_delete_memory(client):
    memory = create_memory(client).json()

    response = client.delete(f"/api/v1/memories/{memory['id']}", headers=HEADERS)

    assert response.status_code == 204
    assert client.get(f"/api/v1/memories/{memory['id']}", headers=HEADERS).status_code == 404


def test_delete_not_found(client):
    response = client.delete("/api/v1/memories/does-not-exist", headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["code"] == "MEMORY_NOT_FOUND"


# --- explicit-by-id regression -------------------------------------------------------


def test_memory_operations_never_require_opening_a_chat_or_course_first(client):
    """No hidden "activate" step: every route works from the ids in the URL/body,
    like the chat routes.
    """
    course = client.post("/api/v1/courses", json={"name": "Physics"}, headers=HEADERS).json()
    memory = create_memory(client, courseId=course["id"]).json()

    # Directly patch/archive/restore/delete without any prior GET/"open".
    client.patch(f"/api/v1/memories/{memory['id']}", json={"topic": "Renamed"}, headers=HEADERS)
    client.post(f"/api/v1/memories/{memory['id']}/archive", headers=HEADERS)
    response = client.post(f"/api/v1/memories/{memory['id']}/restore", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["topic"] == "Renamed"
    assert response.json()["status"] == "active"
