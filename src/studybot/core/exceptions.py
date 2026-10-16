"""Project-specific exceptions.

Expected failures raise one of these so the CLI can show a clean message;
unexpected errors propagate.
"""

from __future__ import annotations


class StudyBotError(Exception):
    """Base class for all expected, handled errors in the application."""


class ConfigurationError(StudyBotError):
    """Raised when application configuration is invalid or unusable."""


class ModelError(StudyBotError):
    """Raised when a model provider fails to produce a response."""


class UnsafeModelOutputError(ModelError):
    """Model output could not be safely separated into answer and reasoning, or
    contained no answer.

    A ``ModelError``, so existing handlers treat it as a failed generation
    (nothing is persisted).
    """


class GenerationDeadlineExceededError(ModelError):
    """A generation exceeded its total time limit. The message contains numbers only."""

    def __init__(self, deadline_seconds: float, elapsed_seconds: float | None = None) -> None:
        self.deadline_seconds = deadline_seconds
        self.elapsed_seconds = elapsed_seconds
        super().__init__(
            f"The model took longer than the {deadline_seconds:g}-second limit to answer, so the "
            "reply was cancelled. Please try again."
        )


class GenerationTokenLimitExceededError(ModelError):
    """A generation hit its token cap before finishing; partial text is discarded.

    The message contains numbers only.
    """

    def __init__(self, max_generated_tokens: int) -> None:
        self.max_generated_tokens = max_generated_tokens
        super().__init__(
            f"The model reached its {max_generated_tokens}-token limit before finishing its answer, "
            "so the reply was discarded. Please try again."
        )


class SessionError(StudyBotError):
    """Invalid chat/course navigation or validation (not found, ambiguous id prefix, empty name, ...).
    """


class ChatNotFoundError(SessionError):
    """An explicit ``chat_id`` operation targeted a chat that does not exist.

    A ``SessionError`` subtype so the API can map it to ``CHAT_NOT_FOUND``.
    """


class ChatBusyError(StudyBotError):
    """A second generation was requested for a chat that already has one in progress.

    Prevents two replies racing to append to the same history.
    """


class CourseNotFoundError(SessionError):
    """An operation referenced a course id that does not exist.

    A ``SessionError`` subtype so the API can map it to ``COURSE_NOT_FOUND``.
    """


class MemoryNotFoundError(SessionError):
    """An operation targeted a learning memory id that does not exist.

    A ``SessionError`` subtype so the API can map it to ``MEMORY_NOT_FOUND``.
    """


class MemoryConflictError(StudyBotError):
    """Creating or reactivating a memory would produce two active memories with the
    same course, normalized topic and kind.

    The opposing-kind case is resolved by archiving, not by this error.
    """


class LibrarySourceNotFoundError(SessionError):
    """An operation targeted a library source id that does not exist."""


class LibraryFileNotFoundError(SessionError):
    """An operation targeted a library file id that does not exist."""


class LibraryStateError(SessionError):
    """A library file state change is not allowed from its current state."""


class LibraryConflictError(StudyBotError):
    """Creating a library source would duplicate an existing one (same kind and location)."""
