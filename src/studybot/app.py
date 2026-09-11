"""Application wiring: builds the core services from configuration.

Any interface (CLI today; a desktop UI or macOS assistant later) constructs
a `StudyBotApp` and talks only to `app.sessions`. Nothing here is
CLI-specific.
"""

from __future__ import annotations

import logging

from studybot.config.settings import Settings
from studybot.core.session_service import SessionService
from studybot.logging_config import configure_logging
from studybot.models.factory import create_model
from studybot.storage.sqlite_repository import SQLiteChatRepository

logger = logging.getLogger(__name__)


class StudyBotApp:
    """Owns the long-lived services for a single run of the application."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        model = create_model(settings)
        settings.ensure_data_dir()
        self._repository = SQLiteChatRepository(settings.database_path)
        self.sessions = SessionService(
            model=model, repository=self._repository, system_prompt=settings.system_prompt
        )
        logger.debug("StudyBotApp initialized with model provider %r", model.name)

    @classmethod
    def from_env(cls) -> "StudyBotApp":
        settings = Settings.from_env()
        configure_logging(settings)
        return cls(settings)

    def close(self) -> None:
        """Release resources (the database connection) held for this run."""
        self._repository.close()
