"""Selects a concrete `ModelProvider` implementation by name.

This is the single place that maps configuration (`model_provider`) to a
concrete backend. Adding a new backend means adding one case here — no
other module needs to change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from studybot.core.exceptions import ConfigurationError
from studybot.models.base import ModelProvider
from studybot.models.mock import MockModel
from studybot.models.ollama import OllamaModel

if TYPE_CHECKING:
    # `studybot.config.settings` transitively imports `studybot.core`, which
    # imports this package, so importing Settings here at runtime would be
    # circular. `from __future__ import annotations` (above) means the
    # `Settings` annotation below is never evaluated at runtime, so it's
    # safe to make this import type-checking-only.
    from studybot.config.settings import Settings


def create_model(settings: Settings) -> ModelProvider:
    provider_name = settings.model_provider

    if provider_name == "mock":
        return MockModel()

    if provider_name == "ollama":
        return OllamaModel(
            model=settings.ollama_model,
            host=settings.ollama_host,
            timeout=settings.ollama_timeout,
            keep_alive=settings.ollama_keep_alive,
        )

    raise ConfigurationError(
        f"Unknown model provider {provider_name!r}. Available providers: 'mock', 'ollama'."
    )
