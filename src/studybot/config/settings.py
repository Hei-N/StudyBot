"""Centralized application configuration.

Settings are plain, validated data. They are constructed once (see
`Settings.from_env`) and passed to whatever needs them, rather than read
from the environment ad hoc throughout the codebase.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from studybot.core.exceptions import ConfigurationError
from studybot.core.prompts import DEFAULT_SYSTEM_PROMPT
from studybot.models.generation import (
    DEFAULT_DEEP_GENERATION_DEADLINE_SECONDS,
    DEFAULT_DEEP_MAX_GENERATED_TOKENS,
    DEFAULT_FAST_GENERATION_DEADLINE_SECONDS,
    DEFAULT_FAST_MAX_GENERATED_TOKENS,
)

_ENV_PREFIX = "STUDYBOT_"
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

# The name of the folder used under the OS application-support directory.
# Kept in one place so the eventual user-facing product name can change
# without touching data-directory logic elsewhere.
_APP_DIR_NAME = "StudyBot"

DATABASE_FILENAME = "studybot.db"

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:4b"
DEFAULT_OLLAMA_TIMEOUT = 120.0


def default_data_dir() -> Path:
    """The OS-appropriate location for this app's *real* persistent data —
    i.e. what `data_dir` resolves to when `STUDYBOT_DATA_DIR` is not set.

    Public (Stage 6.2) specifically so verification tooling can compare a
    resolved `Settings.data_dir` against this and refuse to run a
    destructive operation if they match — see
    `studybot.config.verification_guard`. Nothing else in the app should
    need to call this directly; use `Settings.from_env().data_dir`.
    """
    return Path.home() / "Library" / "Application Support" / _APP_DIR_NAME


@dataclass(frozen=True, slots=True)
class Settings:
    """Application configuration for the current process."""

    environment: str = "development"
    log_level: str = "INFO"
    model_provider: str = "mock"
    data_dir: Path = field(default_factory=default_data_dir)
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    # Ollama-specific. Read only when model_provider == "ollama", but kept
    # on the shared Settings object (like the rest of the app's config)
    # rather than introducing a separate per-provider config type.
    ollama_host: str = DEFAULT_OLLAMA_HOST
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_timeout: float = DEFAULT_OLLAMA_TIMEOUT
    ollama_keep_alive: str | None = None

    # Generation budgets: safety limits per reasoning mode (defaults live in
    # studybot.models.generation).
    fast_max_generated_tokens: int = DEFAULT_FAST_MAX_GENERATED_TOKENS
    deep_max_generated_tokens: int = DEFAULT_DEEP_MAX_GENERATED_TOKENS
    fast_generation_deadline_seconds: float = DEFAULT_FAST_GENERATION_DEADLINE_SECONDS
    deep_generation_deadline_seconds: float = DEFAULT_DEEP_GENERATION_DEADLINE_SECONDS

    def __post_init__(self) -> None:
        # Invalid budgets fail at construction; they are never clamped.
        for name in ("fast_max_generated_tokens", "deep_max_generated_tokens"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ConfigurationError(f"{name} must be a positive integer, got {value!r}")
        for name in ("fast_generation_deadline_seconds", "deep_generation_deadline_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ConfigurationError(f"{name} must be a finite number > 0, got {value!r}")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Build settings from environment variables, falling back to defaults.

        Recognized variables (all optional):
            STUDYBOT_ENV                 e.g. "development" or "production"
            STUDYBOT_LOG_LEVEL           e.g. "DEBUG", "INFO", "WARNING", "ERROR"
            STUDYBOT_MODEL_PROVIDER      "mock" or "ollama"
            STUDYBOT_DATA_DIR            path override for the app data directory
            STUDYBOT_SYSTEM_PROMPT       override the baseline system prompt
            STUDYBOT_OLLAMA_HOST         e.g. "http://localhost:11434"
            STUDYBOT_OLLAMA_MODEL        e.g. "qwen3:4b"
            STUDYBOT_OLLAMA_TIMEOUT      request timeout in seconds
            STUDYBOT_OLLAMA_KEEP_ALIVE   e.g. "5m" (how long Ollama keeps the model loaded)

        `env` may be supplied explicitly (instead of reading `os.environ`) so
        tests can build settings deterministically without mutating global
        process state or touching the real application data directory.
        """
        source = os.environ if env is None else env

        environment = source.get(f"{_ENV_PREFIX}ENV", "development")

        log_level = source.get(f"{_ENV_PREFIX}LOG_LEVEL", "INFO").upper()
        if log_level not in _VALID_LOG_LEVELS:
            raise ConfigurationError(
                f"Invalid {_ENV_PREFIX}LOG_LEVEL {log_level!r}; "
                f"must be one of {sorted(_VALID_LOG_LEVELS)}"
            )

        model_provider = source.get(f"{_ENV_PREFIX}MODEL_PROVIDER", "mock")

        data_dir_override = source.get(f"{_ENV_PREFIX}DATA_DIR")
        data_dir = Path(data_dir_override) if data_dir_override else default_data_dir()

        system_prompt = source.get(f"{_ENV_PREFIX}SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)

        ollama_host = source.get(f"{_ENV_PREFIX}OLLAMA_HOST", DEFAULT_OLLAMA_HOST)
        ollama_model = source.get(f"{_ENV_PREFIX}OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        ollama_keep_alive = source.get(f"{_ENV_PREFIX}OLLAMA_KEEP_ALIVE")

        timeout_raw = source.get(f"{_ENV_PREFIX}OLLAMA_TIMEOUT")
        if timeout_raw is None:
            ollama_timeout = DEFAULT_OLLAMA_TIMEOUT
        else:
            try:
                ollama_timeout = float(timeout_raw)
            except ValueError as exc:
                raise ConfigurationError(
                    f"Invalid {_ENV_PREFIX}OLLAMA_TIMEOUT {timeout_raw!r}; must be a number"
                ) from exc

        def parse(name: str, default, kind):
            raw = source.get(f"{_ENV_PREFIX}{name}")
            if raw is None:
                return default
            try:
                return kind(raw)
            except ValueError as exc:
                what = "an integer" if kind is int else "a number"
                raise ConfigurationError(f"Invalid {_ENV_PREFIX}{name} {raw!r}; must be {what}") from exc

        fast_tokens = parse("FAST_MAX_GENERATED_TOKENS", DEFAULT_FAST_MAX_GENERATED_TOKENS, int)
        deep_tokens = parse("DEEP_MAX_GENERATED_TOKENS", DEFAULT_DEEP_MAX_GENERATED_TOKENS, int)
        fast_deadline = parse("FAST_GENERATION_DEADLINE_SECONDS", DEFAULT_FAST_GENERATION_DEADLINE_SECONDS, float)
        deep_deadline = parse("DEEP_GENERATION_DEADLINE_SECONDS", DEFAULT_DEEP_GENERATION_DEADLINE_SECONDS, float)

        return cls(
            environment=environment,
            log_level=log_level,
            model_provider=model_provider,
            data_dir=data_dir,
            system_prompt=system_prompt,
            ollama_host=ollama_host,
            ollama_model=ollama_model,
            ollama_timeout=ollama_timeout,
            ollama_keep_alive=ollama_keep_alive,
            fast_max_generated_tokens=fast_tokens,
            deep_max_generated_tokens=deep_tokens,
            fast_generation_deadline_seconds=fast_deadline,
            deep_generation_deadline_seconds=deep_deadline,
        )

    @property
    def log_level_int(self) -> int:
        return logging.getLevelNamesMapping()[self.log_level]

    def ensure_data_dir(self) -> Path:
        """Create the application data directory if it doesn't exist yet, and return it."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir

    @property
    def database_path(self) -> Path:
        """Where the local chat-history database lives, inside `data_dir`."""
        return self.data_dir / DATABASE_FILENAME
