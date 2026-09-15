import logging

import pytest
from fastapi.testclient import TestClient

from studybot.api.server import create_app
from studybot.config.settings import Settings

TOKEN = "test-secret-token-value"


@pytest.fixture
def app_and_client(tmp_path):
    settings = Settings.from_env(
        env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)}
    )
    app = create_app(settings=settings, token=TOKEN)
    with TestClient(app) as client:
        yield app, client


@pytest.fixture
def client(app_and_client):
    return app_and_client[1]


def test_missing_token_is_rejected(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_incorrect_token_is_rejected(client):
    response = client.get("/api/v1/health", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_malformed_header_is_rejected(client):
    response = client.get("/api/v1/health", headers={"Authorization": TOKEN})  # missing "Bearer "

    assert response.status_code == 401


def test_valid_token_is_accepted(client):
    response = client.get("/api/v1/health", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200


def test_token_never_appears_in_logs(app_and_client, caplog):
    _, client = app_and_client
    caplog.set_level(logging.DEBUG)

    client.get("/api/v1/health", headers={"Authorization": f"Bearer {TOKEN}"})
    client.get("/api/v1/health", headers={"Authorization": "Bearer wrong-token"})
    client.get("/api/v1/health")

    assert TOKEN not in caplog.text
    assert "wrong-token" not in caplog.text
