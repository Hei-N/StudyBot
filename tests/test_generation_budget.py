"""Tests for the provider-neutral generation budget value types."""

import dataclasses
import math

import pytest

from studybot.core.reasoning_mode import ReasoningMode
from studybot.models.generation import (
    DEFAULT_DEEP_GENERATION_DEADLINE_SECONDS,
    DEFAULT_DEEP_MAX_GENERATED_TOKENS,
    DEFAULT_FAST_GENERATION_DEADLINE_SECONDS,
    DEFAULT_FAST_MAX_GENERATED_TOKENS,
    DEFAULT_GENERATION_BUDGET_POLICY,
    GenerationBudget,
    GenerationBudgetPolicy,
)


def test_a_valid_budget_is_accepted():
    budget = GenerationBudget(2048, 120.0)
    assert budget.max_generated_tokens == 2048
    assert budget.deadline_seconds == 120.0


def test_an_integer_deadline_is_accepted():
    assert GenerationBudget(1, 5).deadline_seconds == 5


@pytest.mark.parametrize("tokens", [0, -1, -2048])
def test_non_positive_token_counts_are_rejected(tokens):
    with pytest.raises(ValueError):
        GenerationBudget(tokens, 120.0)


@pytest.mark.parametrize("tokens", [1.5, 2048.0, "2048", None, True])
def test_non_integer_token_counts_are_rejected(tokens):
    with pytest.raises(ValueError):
        GenerationBudget(tokens, 120.0)


@pytest.mark.parametrize("seconds", [0, 0.0, -1.0, -0.001])
def test_non_positive_deadlines_are_rejected(seconds):
    with pytest.raises(ValueError):
        GenerationBudget(2048, seconds)


@pytest.mark.parametrize("seconds", [math.nan, math.inf, -math.inf])
def test_nan_and_infinite_deadlines_are_rejected(seconds):
    with pytest.raises(ValueError):
        GenerationBudget(2048, seconds)


@pytest.mark.parametrize("seconds", ["120", None, True])
def test_non_numeric_deadlines_are_rejected(seconds):
    with pytest.raises(ValueError):
        GenerationBudget(2048, seconds)


def test_a_budget_is_immutable():
    budget = GenerationBudget(2048, 120.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        budget.max_generated_tokens = 1  # type: ignore[misc]


def test_a_budget_has_no_dynamic_attributes():
    assert not hasattr(GenerationBudget(1, 1.0), "__dict__")


def test_policy_maps_each_mode_to_its_own_budget():
    fast, deep = GenerationBudget(10, 1.0), GenerationBudget(20, 2.0)
    policy = GenerationBudgetPolicy(fast=fast, deep=deep)
    assert policy.for_mode(ReasoningMode.FAST) is fast
    assert policy.for_mode(ReasoningMode.DEEP) is deep


def test_policy_rejects_an_unknown_mode_instead_of_guessing():
    policy = GenerationBudgetPolicy(GenerationBudget(10, 1.0), GenerationBudget(20, 2.0))
    with pytest.raises(ValueError):
        policy.for_mode("turbo")  # type: ignore[arg-type]


def test_policy_is_immutable():
    policy = GenerationBudgetPolicy(GenerationBudget(10, 1.0), GenerationBudget(20, 2.0))
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.fast = GenerationBudget(1, 1.0)  # type: ignore[misc]


def test_exact_default_constants():
    assert DEFAULT_FAST_MAX_GENERATED_TOKENS == 4096
    assert DEFAULT_DEEP_MAX_GENERATED_TOKENS == 6144
    assert DEFAULT_FAST_GENERATION_DEADLINE_SECONDS == 120.0
    assert DEFAULT_DEEP_GENERATION_DEADLINE_SECONDS == 300.0


def test_default_policy_uses_exactly_those_values():
    fast = DEFAULT_GENERATION_BUDGET_POLICY.for_mode(ReasoningMode.FAST)
    deep = DEFAULT_GENERATION_BUDGET_POLICY.for_mode(ReasoningMode.DEEP)
    assert (fast.max_generated_tokens, fast.deadline_seconds) == (4096, 120.0)
    assert (deep.max_generated_tokens, deep.deadline_seconds) == (6144, 300.0)


def test_deep_never_has_a_smaller_budget_than_fast():
    fast = DEFAULT_GENERATION_BUDGET_POLICY.fast
    deep = DEFAULT_GENERATION_BUDGET_POLICY.deep
    assert deep.max_generated_tokens > fast.max_generated_tokens
    assert deep.deadline_seconds > fast.deadline_seconds
