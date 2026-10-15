import logging
from pathlib import Path

import pytest

from studybot.config.settings import (
    DEFAULT_OLLAMA_HOST,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_TIMEOUT,
    Settings,
    default_data_dir,
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
    """Regression: the default must be computed per instance, not once at class
    definition. A ``default_factory`` re-runs ``default_data_dir()`` each time.
    """
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


# --- default_data_dir() (public so verification tooling can compare against it) ----------


def test_default_data_dir_is_public_and_matches_no_override_resolution():
    settings_without_override = Settings.from_env(env={})

    assert settings_without_override.data_dir == default_data_dir()


def test_default_data_dir_is_under_application_support():
    resolved = default_data_dir()

    assert resolved.name == "StudyBot"
    assert resolved.parent.name == "Application Support"


def test_an_unrecognized_env_var_is_silently_ignored_not_an_error():
    """An unrecognized key such as the nonexistent STUDYBOT_DB_PATH is silently
    ignored and falls back to every default, including the real
    ``default_data_dir()``. This is why ``studybot.config.verification_guard``
    exists: ``Settings`` itself cannot catch this mistake.
    """
    settings = Settings.from_env(env={"STUDYBOT_DB_PATH": "/tmp/totally-ignored.db"})

    assert settings.data_dir == default_data_dir()  # the typo'd override had zero effect


# --- generation budgets --------------------------------------------------------------------

BUDGET_ENV = {
    "STUDYBOT_FAST_MAX_GENERATED_TOKENS": "fast_max_generated_tokens",
    "STUDYBOT_DEEP_MAX_GENERATED_TOKENS": "deep_max_generated_tokens",
    "STUDYBOT_FAST_GENERATION_DEADLINE_SECONDS": "fast_generation_deadline_seconds",
    "STUDYBOT_DEEP_GENERATION_DEADLINE_SECONDS": "deep_generation_deadline_seconds",
}
TOKEN_VARS = ["STUDYBOT_FAST_MAX_GENERATED_TOKENS", "STUDYBOT_DEEP_MAX_GENERATED_TOKENS"]
DEADLINE_VARS = ["STUDYBOT_FAST_GENERATION_DEADLINE_SECONDS", "STUDYBOT_DEEP_GENERATION_DEADLINE_SECONDS"]


def test_budget_defaults_come_from_the_generation_module():
    from studybot.models import generation

    settings = Settings.from_env(env={})

    assert settings.fast_max_generated_tokens == generation.DEFAULT_FAST_MAX_GENERATED_TOKENS == 4096
    assert settings.deep_max_generated_tokens == generation.DEFAULT_DEEP_MAX_GENERATED_TOKENS == 6144
    assert settings.fast_generation_deadline_seconds == generation.DEFAULT_FAST_GENERATION_DEADLINE_SECONDS == 120.0
    assert settings.deep_generation_deadline_seconds == generation.DEFAULT_DEEP_GENERATION_DEADLINE_SECONDS == 300.0


@pytest.mark.parametrize("variable", TOKEN_VARS)
def test_each_token_variable_overrides_only_its_own_field(variable):
    settings = Settings.from_env(env={variable: "64"})
    defaults = Settings.from_env(env={})
    for env_name, field_name in BUDGET_ENV.items():
        expected = 64 if env_name == variable else getattr(defaults, field_name)
        assert getattr(settings, field_name) == expected


@pytest.mark.parametrize("variable", DEADLINE_VARS)
def test_each_deadline_variable_overrides_only_its_own_field(variable):
    settings = Settings.from_env(env={variable: "2.5"})
    defaults = Settings.from_env(env={})
    for env_name, field_name in BUDGET_ENV.items():
        expected = 2.5 if env_name == variable else getattr(defaults, field_name)
        assert getattr(settings, field_name) == expected


def test_all_budget_variables_together():
    settings = Settings.from_env(
        env={
            "STUDYBOT_FAST_MAX_GENERATED_TOKENS": "32",
            "STUDYBOT_DEEP_MAX_GENERATED_TOKENS": "64",
            "STUDYBOT_FAST_GENERATION_DEADLINE_SECONDS": "2",
            "STUDYBOT_DEEP_GENERATION_DEADLINE_SECONDS": "9.5",
        }
    )
    assert (settings.fast_max_generated_tokens, settings.deep_max_generated_tokens) == (32, 64)
    assert (settings.fast_generation_deadline_seconds, settings.deep_generation_deadline_seconds) == (2.0, 9.5)


def test_a_pair_of_budget_variables_leaves_the_other_two_at_their_defaults():
    settings = Settings.from_env(
        env={"STUDYBOT_FAST_MAX_GENERATED_TOKENS": "100", "STUDYBOT_DEEP_GENERATION_DEADLINE_SECONDS": "10"}
    )
    assert settings.fast_max_generated_tokens == 100
    assert settings.deep_generation_deadline_seconds == 10.0
    assert settings.deep_max_generated_tokens == 6144
    assert settings.fast_generation_deadline_seconds == 120.0


@pytest.mark.parametrize("variable", TOKEN_VARS)
@pytest.mark.parametrize("bad", ["0", "-1", "-2048", "nan", "inf", "-inf", "abc", "", " ", "1.5", "2e3", "0x10"])
def test_invalid_token_values_fail_configuration(variable, bad):
    with pytest.raises(ConfigurationError):
        Settings.from_env(env={variable: bad})


@pytest.mark.parametrize("variable", DEADLINE_VARS)
@pytest.mark.parametrize("bad", ["0", "0.0", "-1", "-0.5", "nan", "NaN", "inf", "-inf", "Infinity", "abc", "", " "])
def test_invalid_deadline_values_fail_configuration(variable, bad):
    with pytest.raises(ConfigurationError):
        Settings.from_env(env={variable: bad})


def test_an_invalid_budget_error_names_the_offending_variable():
    with pytest.raises(ConfigurationError, match="STUDYBOT_DEEP_MAX_GENERATED_TOKENS"):
        Settings.from_env(env={"STUDYBOT_DEEP_MAX_GENERATED_TOKENS": "abc"})


def test_invalid_budgets_are_never_silently_clamped():
    with pytest.raises(ConfigurationError):
        Settings.from_env(env={"STUDYBOT_FAST_MAX_GENERATED_TOKENS": "-5"})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fast_max_generated_tokens": 0},
        {"deep_max_generated_tokens": -1},
        {"fast_max_generated_tokens": 1.5},
        {"fast_generation_deadline_seconds": 0.0},
        {"deep_generation_deadline_seconds": float("nan")},
        {"deep_generation_deadline_seconds": float("inf")},
    ],
)
def test_constructing_settings_directly_with_an_invalid_budget_also_fails(kwargs):
    with pytest.raises(ConfigurationError):
        Settings(**kwargs)


def test_budget_variables_coexist_with_the_data_dir_override(tmp_path):
    settings = Settings.from_env(
        env={"STUDYBOT_DATA_DIR": str(tmp_path), "STUDYBOT_FAST_MAX_GENERATED_TOKENS": "32"}
    )
    assert settings.data_dir == tmp_path
    assert settings.fast_max_generated_tokens == 32


def test_the_factory_builds_its_policy_from_the_settings_budget_fields():
    from studybot.core.reasoning_mode import ReasoningMode
    from studybot.models.factory import create_model

    settings = Settings.from_env(
        env={
            "STUDYBOT_MODEL_PROVIDER": "ollama",
            "STUDYBOT_FAST_MAX_GENERATED_TOKENS": "32",
            "STUDYBOT_DEEP_MAX_GENERATED_TOKENS": "64",
            "STUDYBOT_FAST_GENERATION_DEADLINE_SECONDS": "2",
            "STUDYBOT_DEEP_GENERATION_DEADLINE_SECONDS": "4",
        }
    )

    model = create_model(settings)

    fast = model._generation_budget(ReasoningMode.FAST)
    deep = model._generation_budget(ReasoningMode.DEEP)
    assert (fast.max_generated_tokens, fast.deadline_seconds) == (32, 2.0)
    assert (deep.max_generated_tokens, deep.deadline_seconds) == (64, 4.0)
