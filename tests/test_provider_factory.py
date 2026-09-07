import pytest

from studybot.config.settings import Settings
from studybot.core.exceptions import ConfigurationError
from studybot.models.factory import create_model
from studybot.models.mock import MockModel
from studybot.models.ollama import OllamaModel
from tests.fake_ollama import FakeListResponse, FakeOllamaClient


def test_factory_resolves_mock_provider():
    settings = Settings.from_env(env={"STUDYBOT_MODEL_PROVIDER": "mock"})

    model = create_model(settings)

    assert isinstance(model, MockModel)


def test_factory_resolves_ollama_provider_without_touching_network():
    # Building an OllamaModel (and the ollama.Client it holds) is designed to
    # be side-effect-free — no connection is attempted until a request is
    # actually made — so this must succeed with no server running and no
    # patched client at all.
    settings = Settings.from_env(
        env={
            "STUDYBOT_MODEL_PROVIDER": "ollama",
            "STUDYBOT_OLLAMA_MODEL": "gemma:2b",
            "STUDYBOT_OLLAMA_HOST": "http://example.local:11434",
        }
    )

    model = create_model(settings)

    assert isinstance(model, OllamaModel)


def test_factory_wires_configured_model_name_into_ollama_provider(monkeypatch):
    fake = FakeOllamaClient(list_response=FakeListResponse([]))
    monkeypatch.setattr("studybot.models.ollama.ollama.Client", lambda **kwargs: fake)

    settings = Settings.from_env(
        env={"STUDYBOT_MODEL_PROVIDER": "ollama", "STUDYBOT_OLLAMA_MODEL": "gemma:2b"}
    )

    model = create_model(settings)
    status = model.get_status()

    assert status.model_name == "gemma:2b"


def test_factory_raises_configuration_error_for_unknown_provider():
    settings = Settings.from_env(env={"STUDYBOT_MODEL_PROVIDER": "some-cloud-thing"})

    with pytest.raises(ConfigurationError):
        create_model(settings)
