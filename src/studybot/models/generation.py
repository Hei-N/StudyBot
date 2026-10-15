"""Provider-neutral generation budgets.

A budget bounds one model request two ways:

* ``max_generated_tokens``: the total tokens the model may generate, including
  hidden reasoning for thinking models. A model that spends its whole allowance
  reasoning produces no answer, and the request fails instead of hanging or
  truncating silently.
* ``deadline_seconds``: a total wall-clock limit for the whole call (reasoning,
  answer and streaming). It is not an inactivity timeout.

The policy chooses a budget from the reasoning mode only, never from the model,
course or teaching mode. These are safety limits, not quality settings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from studybot.core.reasoning_mode import ReasoningMode

DEFAULT_FAST_MAX_GENERATED_TOKENS = 4096
DEFAULT_DEEP_MAX_GENERATED_TOKENS = 6144

DEFAULT_FAST_GENERATION_DEADLINE_SECONDS = 120.0
DEFAULT_DEEP_GENERATION_DEADLINE_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class GenerationBudget:
    max_generated_tokens: int
    deadline_seconds: float

    def __post_init__(self) -> None:
        tokens, seconds = self.max_generated_tokens, self.deadline_seconds
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens <= 0:
            raise ValueError(f"max_generated_tokens must be a positive integer, got {tokens!r}")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError(f"deadline_seconds must be a number, got {seconds!r}")
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError(f"deadline_seconds must be finite and > 0, got {seconds!r}")


@dataclass(frozen=True, slots=True)
class GenerationBudgetPolicy:
    fast: GenerationBudget
    deep: GenerationBudget

    def for_mode(self, reasoning_mode: ReasoningMode) -> GenerationBudget:
        if reasoning_mode is ReasoningMode.FAST:
            return self.fast
        if reasoning_mode is ReasoningMode.DEEP:
            return self.deep
        raise ValueError(f"Unknown reasoning mode: {reasoning_mode!r}")  # no fallback guessing


DEFAULT_GENERATION_BUDGET_POLICY = GenerationBudgetPolicy(
    fast=GenerationBudget(DEFAULT_FAST_MAX_GENERATED_TOKENS, DEFAULT_FAST_GENERATION_DEADLINE_SECONDS),
    deep=GenerationBudget(DEFAULT_DEEP_MAX_GENERATED_TOKENS, DEFAULT_DEEP_GENERATION_DEADLINE_SECONDS),
)
