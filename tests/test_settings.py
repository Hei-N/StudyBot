import logging
from pathlib import Path

import pytest

from studybot.config.settings import Settings
from studybot.core.exceptions import ConfigurationError


def test_defaults_with_empty_environment():
    settings = Settings.from_env(env={})

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.model_provider == "mock"
    assert isinstance(settings.data_dir, Path)


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
