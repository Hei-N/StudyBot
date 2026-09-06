"""Selects a concrete `ModelProvider` implementation by name.

This is the single place that maps configuration (`model_provider`) to a
concrete backend. Stage 1 only knows about "mock"; later stages add cases
here (e.g. "ollama") without any caller needing to change.
"""

from __future__ import annotations

from studybot.core.exceptions import ConfigurationError
from studybot.models.base import ModelProvider
from studybot.models.mock import MockModel


def create_model(provider_name: str) -> ModelProvider:
    if provider_name == "mock":
        return MockModel()

    raise ConfigurationError(
        f"Unknown model provider {provider_name!r}. Available providers: 'mock'."
    )
