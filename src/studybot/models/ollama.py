"""Ollama-backed model provider.

The only module that imports ``ollama``/``httpx`` or depends on Ollama's
request and response shapes; everything else uses the ``ModelProvider``
protocol.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Any, Callable, Iterator, Mapping, Sequence

import httpx
import ollama

from studybot.core.exceptions import (
    GenerationDeadlineExceededError,
    GenerationTokenLimitExceededError,
    ModelError,
)
from studybot.core.output_integrity import ReasoningOutputFilter
from studybot.core.messages import Message, Role
from studybot.core.reasoning_mode import DEFAULT_REASONING_MODE, ReasoningMode
from studybot.models.base import ModelCapabilities, ModelResponse, ProviderStatus
from studybot.models.generation import (
    DEFAULT_GENERATION_BUDGET_POLICY,
    GenerationBudget,
    GenerationBudgetPolicy,
)

logger = logging.getLogger(__name__)

_ROLE_TO_OLLAMA = {
    Role.SYSTEM: "system",
    Role.USER: "user",
    Role.ASSISTANT: "assistant",
}


class ThinkingCapability(Enum):
    """How the configured model handles Ollama's ``think`` parameter, read from ``/api/show``."""

    NONE = "none"  # not a thinking model: `think` must not be sent
    TOGGLEABLE = "toggleable"  # hybrid (e.g. original Qwen3): think on/off both work
    ALWAYS_ON = "always_on"  # thinking-only (e.g. Qwen3-4B-Thinking-2507)
    UNKNOWN = "unknown"  # couldn't tell (probe failed, or an older Ollama)


# Only this module knows Ollama's `think` parameter; callers pass a generic
# ReasoningMode.
_REASONING_MODE_TO_THINK = {
    ReasoningMode.FAST: False,
    ReasoningMode.DEEP: True,
}


def _think_param(capability: ThinkingCapability, mode: ReasoningMode) -> bool | None:
    """Return the ``think`` value to send for this model and reasoning mode.

    A thinking-only model reasons regardless; ``think=False`` would only stop
    Ollama from separating the reasoning, leaking it into ``content``. Such
    models always get ``think=True``, so Fast and Deep behave the same for them.
    """
    if capability is ThinkingCapability.ALWAYS_ON:
        return True
    if capability is ThinkingCapability.NONE:
        return None
    return _REASONING_MODE_TO_THINK[mode]


def parse_thinking_capability(show_payload: dict[str, Any]) -> ThinkingCapability:
    """Classify a raw ``/api/show`` payload.

    ``capabilities`` says whether the model thinks; ``thinking.values`` says which
    ``think`` settings it accepts (``[true]`` = thinking-only, ``[true, false]`` =
    toggleable). Missing or unexpected data is UNKNOWN.
    """
    capabilities = show_payload.get("capabilities")
    if not isinstance(capabilities, list):
        return ThinkingCapability.UNKNOWN
    if "thinking" not in capabilities:
        return ThinkingCapability.NONE
    thinking = show_payload.get("thinking")
    values = thinking.get("values") if isinstance(thinking, dict) else None
    if not isinstance(values, list) or True not in values:
        return ThinkingCapability.UNKNOWN
    return ThinkingCapability.TOGGLEABLE if False in values else ThinkingCapability.ALWAYS_ON


def _capability_flag(show_payload: dict[str, Any], name: str) -> bool | None:
    """True/False if ``capabilities`` is a valid list (flag present/absent); None if
    it is missing or malformed.
    """
    capabilities = show_payload.get("capabilities")
    if not isinstance(capabilities, list):
        return None
    return name in capabilities


def _context_window(show_payload: dict[str, Any]) -> int | None:
    """Largest positive integer under a ``*.context_length`` key of ``model_info``,
    or None. The key is prefixed with the model family, hence the suffix match.
    """
    model_info = show_payload.get("model_info")
    if not isinstance(model_info, dict):
        return None
    lengths = [
        value
        for key, value in model_info.items()
        if isinstance(key, str)
        and key.endswith(".context_length")
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
    ]
    return max(lengths) if lengths else None


def _thinking_flags(capability: ThinkingCapability) -> tuple[bool | None, bool | None]:
    """(supports_thinking, reasoning_modes_distinct) for a classification."""
    if capability is ThinkingCapability.TOGGLEABLE:
        return True, True
    if capability is ThinkingCapability.ALWAYS_ON:
        return True, False  # Fast and Deep must both reason (output integrity)
    if capability is ThinkingCapability.NONE:
        return False, False
    return None, None


def capabilities_from_show(
    show_payload: dict[str, Any] | None, thinking: ThinkingCapability
) -> ModelCapabilities:
    """Build ``ModelCapabilities`` from a raw ``/api/show`` payload (None if the
    lookup failed).

    ``thinking`` normally comes from the same payload, but a constructor-pinned
    value takes precedence.
    """
    supports_thinking, modes_distinct = _thinking_flags(thinking)
    if show_payload is None:
        return ModelCapabilities(None, None, supports_thinking, modes_distinct, None)
    return ModelCapabilities(
        supports_vision=_capability_flag(show_payload, "vision"),
        supports_tools=_capability_flag(show_payload, "tools"),
        supports_thinking=supports_thinking,
        reasoning_modes_distinct=modes_distinct,
        context_window=_context_window(show_payload),
    )

_MODEL_NOT_FOUND_STATUS = 404

# A refused connection surfaces as ConnectionError or httpx.ConnectError
# depending on the code path; both are handled the same way.
_CONNECTION_ERRORS = (ConnectionError, httpx.ConnectError)


# `done_reason` on the final chunk when generation stopped at the
# `num_predict` cap rather than finishing ("stop").
_DONE_REASON_LENGTH = "length"


def _merge_options(existing: Mapping[str, Any] | None, budget: GenerationBudget) -> dict[str, Any]:
    """Return request options with the token cap applied as ``num_predict``.

    Never mutates the caller's dict and adds nothing else (notably not ``num_ctx``).
    """
    merged = dict(existing) if existing else {}
    merged["num_predict"] = budget.max_generated_tokens
    return merged


def _close_stream_safely(stream: object) -> None:
    """Close a stream if it has ``close()``.

    Never raises, so cleanup cannot mask the original error; logs only the
    exception type.
    """
    close = getattr(stream, "close", None)
    if callable(close):
        try:
            close()
        except Exception as exc:
            logger.debug("Error while closing the model stream (%s)", type(exc).__name__)


def _to_ollama_messages(messages: Sequence[Message]) -> list[dict[str, str]]:
    """Convert typed messages to Ollama chat dicts, preserving order."""
    return [{"role": _ROLE_TO_OLLAMA[m.role], "content": m.content} for m in messages]


class OllamaModel:
    """Model provider backed by a local Ollama server.

    Construction makes no network calls; the client connects on the first request.
    """

    def __init__(
        self,
        model: str,
        host: str = "http://localhost:11434",
        timeout: float | None = 120.0,
        keep_alive: str | float | None = None,
        client: ollama.Client | None = None,
        thinking_capability: ThinkingCapability | None = None,
        show_fetcher: Callable[[], dict[str, Any]] | None = None,
        generation_budget_policy: GenerationBudgetPolicy = DEFAULT_GENERATION_BUDGET_POLICY,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """``client`` is a test seam; leave it unset to build a real ``ollama.Client``.

        ``thinking_capability`` pins the model's thinking behavior. When unset it is
        read lazily from ``/api/show`` via ``show_fetcher`` (a test seam; the
        ``ollama`` package's own ``show()`` drops the ``thinking`` field). Only
        successful lookups are cached, so a failure is retried on the next request.

        ``generation_budget_policy`` bounds every request by reasoning mode. ``clock``
        measures the generation deadline and must be monotonic.
        """
        self._model = model
        self._host = host
        self._timeout = timeout
        self._keep_alive = keep_alive
        self._client = client if client is not None else ollama.Client(host=host, timeout=timeout)
        self._pinned_thinking = thinking_capability
        self._show_fetcher = show_fetcher if show_fetcher is not None else self._fetch_show_payload
        # One non-reentrant lock guards the cached /api/show payload. Derived
        # values are computed outside the lock, so it is never re-acquired,
        # and concurrent first calls wait for a single fetch.
        self._generation_budget_policy = generation_budget_policy
        self._clock = clock
        self._show_lock = threading.Lock()
        self._show_payload: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        return "ollama"

    def _show_metadata(self) -> dict[str, Any] | None:
        """Return the ``/api/show`` payload, fetched lazily.

        Only a successful fetch is cached; a failure returns None and is retried on
        the next call.
        """
        with self._show_lock:
            if self._show_payload is not None:
                return self._show_payload
            try:
                payload = self._show_fetcher()
            except Exception as exc:  # any failure: stay safe, retry next time
                logger.debug("Could not read model metadata from Ollama", exc_info=exc)
                return None
            if not isinstance(payload, dict):
                logger.debug("Ollama model metadata had an unexpected shape")
                return None
            self._show_payload = payload
            logger.info(
                "Model %s thinking capability: %s",
                self._model,
                parse_thinking_capability(payload).value,
            )
            return payload

    def thinking_capability(self) -> ThinkingCapability:
        """Return the model's thinking behavior.

        A constructor-pinned value takes precedence and avoids the lookup.
        """
        if self._pinned_thinking is not None:
            return self._pinned_thinking
        payload = self._show_metadata()
        return ThinkingCapability.UNKNOWN if payload is None else parse_thinking_capability(payload)

    def get_capabilities(self) -> ModelCapabilities:
        """Return provider-neutral capabilities discovered from ``/api/show``.

        If the lookup fails, vision, tools and context are None; a pinned thinking
        capability still fills the thinking fields.
        """
        payload = self._show_metadata()
        if self._pinned_thinking is not None:
            thinking = self._pinned_thinking
        else:
            thinking = ThinkingCapability.UNKNOWN if payload is None else parse_thinking_capability(payload)
        return capabilities_from_show(payload, thinking)

    def _fetch_show_payload(self) -> dict[str, Any]:
        response = httpx.post(
            f"{self._host.rstrip('/')}/api/show", json={"model": self._model}, timeout=self._timeout
        )
        response.raise_for_status()
        return response.json()

    def _request_plan(self, reasoning_mode: ReasoningMode) -> tuple[bool | None, bool]:
        """Return (``think`` value to send, whether the output filter must assume
        reasoning can start without an opening tag).
        """
        capability = self.thinking_capability()
        think = _think_param(capability, reasoning_mode)
        implicit_open = capability is ThinkingCapability.UNKNOWN and think is False
        return think, implicit_open

    def _generation_budget(self, reasoning_mode: ReasoningMode) -> GenerationBudget:
        return self._generation_budget_policy.for_mode(reasoning_mode)

    def generate(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> ModelResponse:
        # Same primitive as stream(), so budget, deadline, filter and
        # done_reason handling cannot drift. "" chunks are progress signals.
        content = "".join(chunk for chunk in self._generate_visible(messages, reasoning_mode) if chunk)
        return ModelResponse(content=content, model_name=self._model)

    def stream(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> Iterator[str]:
        yield from self._generate_visible(messages, reasoning_mode)

    def _generate_visible(self, messages: Sequence[Message], reasoning_mode: ReasoningMode) -> Iterator[str]:
        """Yield filtered visible text (and ``""`` progress signals) under the generation budget.

        Per raw chunk: reasoning filtering, then the deadline check, then exposure.
        A ``done_reason`` of "length" is checked before the filter's "no answer"
        check, so a model that spent its whole token allowance reasoning is reported
        as a token-limit failure rather than an empty answer. The ``thinking`` field
        is never read.
        """
        think, implicit_open = self._request_plan(reasoning_mode)
        budget = self._generation_budget(reasoning_mode)
        output_filter = ReasoningOutputFilter(implicit_open=implicit_open)
        started = self._clock()
        deadline = started + budget.deadline_seconds
        raw_chunks = 0
        visible_chars = 0
        done_reason: str | None = None
        stream: object = None

        def check_deadline() -> None:
            if self._clock() >= deadline:
                raise GenerationDeadlineExceededError(budget.deadline_seconds, self._clock() - started)

        try:
            stream = self._client.chat(
                model=self._model,
                messages=_to_ollama_messages(messages),
                stream=True,
                think=think,
                keep_alive=self._keep_alive,
                options=_merge_options(None, budget),
            )
            for chunk in stream:
                raw_chunks += 1
                check_deadline()  # before processing the newly received chunk
                reason = getattr(chunk, "done_reason", None)
                if reason:
                    done_reason = reason
                content = chunk.message.content
                visible = output_filter.feed(content) if content else ""
                check_deadline()  # again, before anything becomes visible
                visible_chars += len(visible)
                # Yield "" progress signals so the engine thread can serve
                # other requests while the model reasons. They never reset the
                # deadline.
                yield visible
            if done_reason == _DONE_REASON_LENGTH:
                raise GenerationTokenLimitExceededError(budget.max_generated_tokens)
            check_deadline()
            tail = output_filter.finish()
            if tail:
                visible_chars += len(tail)
                yield tail
            self._log_filter_stats(output_filter)
        except GenerationDeadlineExceededError:
            self._log_budget_failure("deadline", reasoning_mode, budget, started, visible_chars, raw_chunks)
            raise
        except GenerationTokenLimitExceededError:
            self._log_budget_failure("token_limit", reasoning_mode, budget, started, visible_chars, raw_chunks)
            raise
        except ModelError:
            raise  # e.g. UnsafeModelOutputError from the filter: already user-facing
        except _CONNECTION_ERRORS as exc:
            raise self._connection_error(exc) from exc
        except ollama.ResponseError as exc:
            raise self._response_error(exc) from exc
        except httpx.TimeoutException as exc:
            raise self._timeout_error(exc) from exc
        except Exception as exc:
            raise self._unexpected_error(exc) from exc
        finally:
            # Always close, including when the consumer abandons the
            # generator; closing makes Ollama stop generating.
            _close_stream_safely(stream)

    def _log_budget_failure(
        self,
        kind: str,
        reasoning_mode: ReasoningMode,
        budget: GenerationBudget,
        started: float,
        visible_chars: int,
        raw_chunks: int,
    ) -> None:
        # Safe metadata only: no prompt, answer or reasoning text.
        logger.warning(
            "Generation stopped: kind=%s model=%s mode=%s max_generated_tokens=%d deadline_seconds=%g "
            "elapsed_ms=%d visible_chars=%d chunks=%d",
            kind,
            self._model,
            reasoning_mode.value,
            budget.max_generated_tokens,
            budget.deadline_seconds,
            int((self._clock() - started) * 1000),
            visible_chars,
            raw_chunks,
        )

    def get_status(self) -> ProviderStatus:
        try:
            listing = self._client.list()
        except _CONNECTION_ERRORS:
            return ProviderStatus(
                provider_name=self.name,
                server_reachable=False,
                model_name=self._model,
                model_available=None,
                detail="Could not connect to the local Ollama service.",
            )
        except Exception as exc:  # unexpected: still report status, don't crash /status
            logger.debug("Unexpected error while checking Ollama status", exc_info=exc)
            return ProviderStatus(
                provider_name=self.name,
                server_reachable=False,
                model_name=self._model,
                model_available=None,
                detail="Unexpected error while contacting Ollama.",
            )

        available = {entry.model for entry in listing.models if entry.model}
        target = self._model
        normalized_target = target if ":" in target else f"{target}:latest"
        model_available = target in available or normalized_target in available

        return ProviderStatus(
            provider_name=self.name,
            server_reachable=True,
            model_name=self._model,
            model_available=model_available,
        )

    def _log_filter_stats(self, output_filter: ReasoningOutputFilter) -> None:
        stats = output_filter.stats
        if stats.reasoning_spans:
            # Counts only; never the reasoning or answer text itself.
            logger.info(
                "Removed %d inline reasoning span(s) (%d chars) from model output",
                stats.reasoning_spans,
                stats.reasoning_chars_discarded,
            )

    def _connection_error(self, exc: Exception) -> ModelError:
        logger.debug("Ollama connection error", exc_info=exc)
        return ModelError(
            "Could not connect to the local Ollama service. "
            f"Is Ollama running at {self._host}? Try: ollama serve"
        )

    def _response_error(self, exc: ollama.ResponseError) -> ModelError:
        logger.debug("Ollama response error: %s", exc, exc_info=exc)
        if exc.status_code == _MODEL_NOT_FOUND_STATUS:
            return ModelError(
                f"Model '{self._model}' is not available locally. "
                f"Run: ollama pull {self._model}"
            )
        return ModelError(f"Ollama request failed: {exc.error}")

    def _timeout_error(self, exc: Exception) -> ModelError:
        logger.debug("Ollama request timed out", exc_info=exc)
        return ModelError(
            f"The local Ollama service did not respond in time (model {self._model!r})."
        )

    def _unexpected_error(self, exc: Exception) -> ModelError:
        logger.error("Unexpected error talking to Ollama", exc_info=exc)
        return ModelError("Ollama request failed unexpectedly. See logs for details.")
