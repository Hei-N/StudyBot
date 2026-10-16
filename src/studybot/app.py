"""Application wiring: builds the core services from configuration.

Any interface constructs a ``StudyBotApp`` and talks to ``app.sessions``,
``app.courses``, ``app.memories`` and ``app.library``. Nothing here is CLI-specific.
"""

from __future__ import annotations

import logging

from studybot.config.settings import Settings
from studybot.core.course_service import CourseService
from studybot.core.library_service import LibraryService
from studybot.core.memory_service import LearningMemoryService
from studybot.core.session_service import SessionService
from studybot.logging_config import configure_logging
from studybot.models.factory import create_model
from studybot.storage.database import open_database
from studybot.storage.sqlite_course_repository import SQLiteCourseRepository
from studybot.storage.sqlite_library_repository import SQLiteLibraryRepository
from studybot.storage.sqlite_learning_memory_repository import SQLiteLearningMemoryRepository
from studybot.storage.sqlite_repository import SQLiteChatRepository

logger = logging.getLogger(__name__)


class StudyBotApp:
    """Owns the long-lived services for a single run of the application."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        model = create_model(settings)
        settings.ensure_data_dir()

        self._connection = open_database(settings.database_path)
        chat_repository = SQLiteChatRepository(self._connection)
        course_repository = SQLiteCourseRepository(self._connection)
        memory_repository = SQLiteLearningMemoryRepository(self._connection)

        self.courses = CourseService(course_repository=course_repository, chat_repository=chat_repository)
        self.memories = LearningMemoryService(
            repository=memory_repository, course_repository=course_repository, chat_repository=chat_repository
        )
        self.library = LibraryService(
            repository=SQLiteLibraryRepository(self._connection), course_repository=course_repository
        )
        self.sessions = SessionService(
            model=model,
            repository=chat_repository,
            course_repository=course_repository,
            system_prompt=settings.system_prompt,
            memory_service=self.memories,
        )
        logger.debug("StudyBotApp initialized with model provider %r", model.name)

    @classmethod
    def from_env(cls) -> "StudyBotApp":
        settings = Settings.from_env()
        configure_logging(settings)
        return cls(settings)

    def close(self) -> None:
        """Release resources (the database connection) held for this run."""
        self._connection.close()
