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
