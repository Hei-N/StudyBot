"""Centralized application configuration.

Settings are plain, validated data. They are constructed once (see
`Settings.from_env`) and passed to whatever needs them, rather than read
from the environment ad hoc throughout the codebase.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from studybot.core.exceptions import ConfigurationError

_ENV_PREFIX = "STUDYBOT_"
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

# The name of the folder used under the OS application-support directory.
# Kept in one place so the eventual user-facing product name can change
# without touching data-directory logic elsewhere.
_APP_DIR_NAME = "StudyBot"


def _default_data_dir() -> Path:
    """The OS-appropriate location for this app's persistent data.

    Nothing is written here yet in Stage 1 (no chats, memory, or indexes are
    persisted) — this only establishes where future stages should write.
    """
    return Path.home() / "Library" / "Application Support" / _APP_DIR_NAME


@dataclass(frozen=True, slots=True)
class Settings:
    """Application configuration for the current process."""

    environment: str = "development"
    log_level: str = "INFO"
    model_provider: str = "mock"
    data_dir: Path = _default_data_dir()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Build settings from environment variables, falling back to defaults.

        Recognized variables (all optional):
            STUDYBOT_ENV            e.g. "development" or "production"
            STUDYBOT_LOG_LEVEL      e.g. "DEBUG", "INFO", "WARNING", "ERROR"
            STUDYBOT_MODEL_PROVIDER e.g. "mock"
            STUDYBOT_DATA_DIR       path override for the app data directory

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
        data_dir = Path(data_dir_override) if data_dir_override else _default_data_dir()

        return cls(
            environment=environment,
            log_level=log_level,
            model_provider=model_provider,
            data_dir=data_dir,
        )

    @property
    def log_level_int(self) -> int:
        return logging.getLevelNamesMapping()[self.log_level]

    def ensure_data_dir(self) -> Path:
        """Create the application data directory if it doesn't exist yet, and return it."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir
