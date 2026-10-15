"""Selects a concrete ``ModelProvider`` from configuration.

Adding a backend means adding one case here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from studybot.core.exceptions import ConfigurationError
from studybot.models.base import ModelProvider
from studybot.models.generation import GenerationBudget, GenerationBudgetPolicy
from studybot.models.mock import MockModel
from studybot.models.ollama import OllamaModel

if TYPE_CHECKING:
    # Type-checking only: importing Settings at runtime would be circular
    # (settings -> core -> models).
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
            generation_budget_policy=GenerationBudgetPolicy(
                fast=GenerationBudget(
                    settings.fast_max_generated_tokens, settings.fast_generation_deadline_seconds
                ),
                deep=GenerationBudget(
                    settings.deep_max_generated_tokens, settings.deep_generation_deadline_seconds
                ),
            ),
        )

    raise ConfigurationError(
        f"Unknown model provider {provider_name!r}. Available providers: 'mock', 'ollama'."
    )
