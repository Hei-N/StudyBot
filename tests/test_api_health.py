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
