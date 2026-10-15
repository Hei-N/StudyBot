import pytest
from fastapi.testclient import TestClient

from studybot.api.server import create_app
from studybot.config.settings import Settings

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def make_client(tmp_path, env_overrides=None):
    env = {"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)}
    env.update(env_overrides or {})
    settings = Settings.from_env(env=env)
    app = create_app(settings=settings, token=TOKEN)
    return TestClient(app)


def test_health_reports_ok_for_mock_backend(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/api/v1/health", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider"] == "mock"
    assert body["model"] == "mock"
    assert body["providerReachable"] is True
    assert body["modelAvailable"] is True


def test_health_reports_api_version(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/api/v1/health", headers=HEADERS)

    assert response.json()["apiVersion"] == "1"


def test_health_reports_unavailable_ollama_provider(tmp_path):
    with make_client(
        tmp_path,
        {"STUDYBOT_MODEL_PROVIDER": "ollama", "STUDYBOT_OLLAMA_HOST": "http://127.0.0.1:1"},
    ) as client:
        response = client.get("/api/v1/health", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "ollama"
    assert body["providerReachable"] is False
    assert body["modelAvailable"] is None


def test_health_requires_auth(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 401


# --- health after generation budget failures -----------------------------------------


@pytest.mark.parametrize("kind", ["deadline", "token_limit"])
def test_health_stays_ok_and_the_provider_stays_reachable_after_a_budget_failure(tmp_path, monkeypatch, kind):
    import studybot.app as app_module
    from tests.fake_ollama import flaky_budget_model

    model, _ = flaky_budget_model(kind)
    monkeypatch.setattr(app_module, "create_model", lambda settings: model)
    with make_client(tmp_path) as client:
        chat_id = client.post("/api/v1/chats", json={}, headers=HEADERS).json()["id"]
        with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
            ws.send_json({"type": "send_message", "chat_id": chat_id, "content": "hi"})
            while (event := ws.receive_json())["type"] not in ("message_completed", "error"):
                pass
            assert event["type"] == "error"

        health = client.get("/api/v1/health", headers=HEADERS)

    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["providerReachable"] is True  # live status from the (budget-failed) provider
    assert body["modelAvailable"] is True
