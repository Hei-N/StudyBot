"""Application wiring: builds the core services from configuration.

Any interface (CLI today; a desktop UI or macOS assistant later) constructs
a `StudyBotApp` and talks only to `app.chat`. Nothing here is CLI-specific.
"""

from __future__ import annotations

import logging

from studybot.config.settings import Settings
from studybot.core.chat import ChatService
from studybot.logging_config import configure_logging
from studybot.models.factory import create_model

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = "You are Study Bot, a local study assistant."


class StudyBotApp:
    """Owns the long-lived services for a single run of the application."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        model = create_model(settings.model_provider)
        self.chat = ChatService(model=model, system_prompt=_SYSTEM_PROMPT)
        logger.debug("StudyBotApp initialized with model provider %r", model.name)

    @classmethod
    def from_env(cls) -> "StudyBotApp":
        settings = Settings.from_env()
        configure_logging(settings)
        return cls(settings)
