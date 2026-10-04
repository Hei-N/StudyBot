"""Project-specific exceptions.

Expected failures should raise one of these so the CLI can show a clean
message instead of a raw traceback. Truly unexpected errors are allowed to
propagate and be logged for debugging.
"""

from __future__ import annotations


class StudyBotError(Exception):
    """Base class for all expected, handled errors in the application."""


class ConfigurationError(StudyBotError):
    """Raised when application configuration is invalid or unusable."""


class ModelError(StudyBotError):
    """Raised when a model provider fails to produce a response."""


class UnsafeModelOutputError(ModelError):
    """The model's output could not be safely separated into a user-facing
    answer and internal reasoning (Stage 6.3), or contained no answer at
    all. The generation fails closed: nothing further is streamed, nothing
    is persisted as an assistant message. A `ModelError` subtype, so every
    existing caller (WebSocket `MODEL_ERROR`, CLI error display, the
    "persist only the user message on failure" guarantee) handles it with
    no changes."""


class SessionError(StudyBotError):
    """Raised for invalid chat/course navigation or validation: not found,
    an ambiguous id prefix, an empty/too-long name, and the like."""


class ChatNotFoundError(SessionError):
    """Raised specifically when an explicit `chat_id` operation targets a
    chat that doesn't exist (Stage 5.8's explicit-by-id API surface).

    A subtype of `SessionError` — a bare `except SessionError` (as CLI code
    already uses in several places) keeps working unchanged — but distinct
    enough that the API layer can map it to `CHAT_NOT_FOUND` precisely,
    without string-matching an exception message to tell "chat not found"
    apart from other `SessionError`s (e.g. "course not found", "empty
    title") raised alongside it in the same call.
    """


class ChatBusyError(StudyBotError):
    """Raised when a second generation (`send_to_chat`/
    `send_streaming_to_chat`) is requested for a chat that already has one
    in progress. See `SessionService`'s per-chat generation lock — the
    goal is to prevent two assistant replies from racing and appending to
    a chat's history in a nondeterministic order, never to make one
    request wait for another."""


class CourseNotFoundError(SessionError):
    """Raised specifically when an operation references a course id that
    doesn't exist. A `SessionError` subtype (like `ChatNotFoundError`) so a
    bare `except SessionError` keeps working; introduced for
    `LearningMemoryService`, which (unlike `CourseService`) can raise both
    a course-not-found and other kinds of `SessionError` from the same
    call and needs to tell them apart precisely at the API layer."""


class MemoryNotFoundError(SessionError):
    """Raised when an operation targets a learning memory id that doesn't
    exist. A `SessionError` subtype (like `ChatNotFoundError`) so a bare
    `except SessionError` keeps working, while the API layer can map it to
    `MEMORY_NOT_FOUND` precisely."""


class MemoryConflictError(StudyBotError):
    """Raised when creating (or reactivating) a learning memory would
    produce two *active* memories for the same course with the same
    normalized topic and the same kind (Stage 6's exact-duplicate policy —
    see `LearningMemoryService`). Not raised for a topic whose *opposite*
    learning state already exists — that case is resolved automatically by
    archiving the superseded entry instead of raising."""
