import logging
from pathlib import Path

import pytest

from studybot.config.settings import (
    DEFAULT_OLLAMA_HOST,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_TIMEOUT,
    Settings,
)
from studybot.core.exceptions import ConfigurationError
from studybot.core.prompts import DEFAULT_SYSTEM_PROMPT


def test_defaults_with_empty_environment():
    settings = Settings.from_env(env={})

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.model_provider == "mock"
    assert isinstance(settings.data_dir, Path)
    assert settings.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert settings.ollama_host == DEFAULT_OLLAMA_HOST
    assert settings.ollama_model == DEFAULT_OLLAMA_MODEL
    assert settings.ollama_timeout == DEFAULT_OLLAMA_TIMEOUT
    assert settings.ollama_keep_alive is None


def test_env_overrides_are_applied():
    settings = Settings.from_env(
        env={
            "STUDYBOT_ENV": "production",
            "STUDYBOT_LOG_LEVEL": "debug",
            "STUDYBOT_MODEL_PROVIDER": "mock",
        }
    )

    assert settings.environment == "production"
    assert settings.log_level == "DEBUG"
    assert settings.model_provider == "mock"


def test_data_dir_override_avoids_real_app_data_directory(tmp_path):
    custom_dir = tmp_path / "studybot-test-data"

    settings = Settings.from_env(env={"STUDYBOT_DATA_DIR": str(custom_dir)})

    assert settings.data_dir == custom_dir


def test_invalid_log_level_raises_configuration_error():
    with pytest.raises(ConfigurationError):
        Settings.from_env(env={"STUDYBOT_LOG_LEVEL": "NOT_A_LEVEL"})


def test_log_level_int_matches_logging_module():
    settings = Settings.from_env(env={"STUDYBOT_LOG_LEVEL": "WARNING"})

    assert settings.log_level_int == logging.WARNING


def test_ensure_data_dir_creates_directory(tmp_path):
    custom_dir = tmp_path / "nested" / "studybot-data"
    settings = Settings.from_env(env={"STUDYBOT_DATA_DIR": str(custom_dir)})

    result = settings.ensure_data_dir()

    assert result == custom_dir
    assert custom_dir.is_dir()


def test_data_dir_default_is_evaluated_per_instance_not_at_class_definition_time(monkeypatch):
    """Regression test: the Stage 1 default was computed once at class-body
    evaluation time (a plain expression default), so every `Settings()`
    shared one frozen default no matter what `Path.home()` returned later.
    A `default_factory` re-runs `_default_data_dir()` on each instantiation."""
    monkeypatch.setattr(Path, "home", lambda: Path("/tmp/studybot-home-one"))
    first = Settings()

    monkeypatch.setattr(Path, "home", lambda: Path("/tmp/studybot-home-two"))
    second = Settings()

    assert first.data_dir == Path("/tmp/studybot-home-one/Library/Application Support/StudyBot")
    assert second.data_dir == Path("/tmp/studybot-home-two/Library/Application Support/StudyBot")


def test_ollama_env_overrides_are_applied():
    settings = Settings.from_env(
        env={
            "STUDYBOT_MODEL_PROVIDER": "ollama",
            "STUDYBOT_OLLAMA_HOST": "http://example.local:11434",
            "STUDYBOT_OLLAMA_MODEL": "qwen3:8b",
            "STUDYBOT_OLLAMA_TIMEOUT": "30",
            "STUDYBOT_OLLAMA_KEEP_ALIVE": "10m",
        }
    )

    assert settings.model_provider == "ollama"
    assert settings.ollama_host == "http://example.local:11434"
    assert settings.ollama_model == "qwen3:8b"
    assert settings.ollama_timeout == 30.0
    assert settings.ollama_keep_alive == "10m"


def test_invalid_ollama_timeout_raises_configuration_error():
    with pytest.raises(ConfigurationError):
        Settings.from_env(env={"STUDYBOT_OLLAMA_TIMEOUT": "not-a-number"})


def test_system_prompt_env_override():
    settings = Settings.from_env(env={"STUDYBOT_SYSTEM_PROMPT": "Custom prompt."})

    assert settings.system_prompt == "Custom prompt."


def test_mock_provider_still_works_without_any_ollama_configuration():
    settings = Settings.from_env(env={"STUDYBOT_MODEL_PROVIDER": "mock"})

    assert settings.model_provider == "mock"
    # Ollama fields still get sensible defaults even though they're unused.
    assert settings.ollama_model == DEFAULT_OLLAMA_MODEL
