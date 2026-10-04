"""Ollama-backed model provider.

This is the only module in the application allowed to import `ollama` (or
its `httpx` transport) or know anything about its request/response shapes.
Everything else talks to the `ModelProvider` protocol.
"""

from __future__ import annotations

import logging
import threading
from enum import Enum
from typing import Any, Callable, Iterator, Sequence

import httpx
import ollama

from studybot.core.exceptions import ModelError
from studybot.core.output_integrity import ReasoningOutputFilter
from studybot.core.messages import Message, Role
from studybot.core.reasoning_mode import DEFAULT_REASONING_MODE, ReasoningMode
from studybot.models.base import ModelResponse, ProviderStatus

logger = logging.getLogger(__name__)

_ROLE_TO_OLLAMA = {
    Role.SYSTEM: "system",
    Role.USER: "user",
    Role.ASSISTANT: "assistant",
}


class ThinkingCapability(Enum):
    """What the configured model does with Ollama's `think` parameter, read
    from `/api/show` (Stage 6.3)."""

    NONE = "none"  # not a thinking model: `think` must not be sent
    TOGGLEABLE = "toggleable"  # hybrid (e.g. original Qwen3): think on/off both work
    ALWAYS_ON = "always_on"  # thinking-only (e.g. Qwen3-4B-Thinking-2507)
    UNKNOWN = "unknown"  # couldn't tell (probe failed, or an older Ollama)


# The only place that knows Qwen/Ollama's `think` request parameter exists
# — ChatService/SessionService only ever pass a generic ReasoningMode.
_REASONING_MODE_TO_THINK = {
    ReasoningMode.FAST: False,
    ReasoningMode.DEEP: True,
}


def _think_param(capability: ThinkingCapability, mode: ReasoningMode) -> bool | None:
    """The `think` value to send for this model and reasoning mode.

    A thinking-only model reasons whether or not it's asked to; sending
    `think=False` only stops Ollama from *separating* that reasoning, so it
    lands in `content` (the Stage 6.3 leak). Such a model therefore always
    gets `think=True` — Fast and Deep behave the same for it (there is no
    faster mode to offer), which is documented rather than hidden.
    """
    if capability is ThinkingCapability.ALWAYS_ON:
        return True
    if capability is ThinkingCapability.NONE:
        return None
    return _REASONING_MODE_TO_THINK[mode]


def parse_thinking_capability(show_payload: dict[str, Any]) -> ThinkingCapability:
    """Classify a raw `/api/show` JSON payload.

    `capabilities` says whether the model thinks at all; the `thinking`
    object's `values` says which `think` settings it honours
    (`[true]` = thinking-only, `[true, false]` = toggleable). Anything
    missing or unexpected is UNKNOWN, never a guess.
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

_MODEL_NOT_FOUND_STATUS = 404

# The `ollama` package wraps a refused/unreachable connection as a plain
# `ConnectionError` on its non-streaming request path, but its streaming
# path talks to httpx directly and lets `httpx.ConnectError` escape
# unwrapped. Both mean the same thing to us, so both are treated the same.
_CONNECTION_ERRORS = (ConnectionError, httpx.ConnectError)


def _to_ollama_messages(messages: Sequence[Message]) -> list[dict[str, str]]:
    """Convert our typed messages to Ollama's chat message dicts, in order."""
    return [{"role": _ROLE_TO_OLLAMA[m.role], "content": m.content} for m in messages]


class OllamaModel:
    """Talks to a local Ollama server via the official `ollama` Python client.

    Construction never touches the network — the client connects lazily on
    the first request, so simply choosing this provider (without sending a
    message) does not require Ollama to be running.
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
    ) -> None:
        """`client` is an injection seam for tests (a fake with `.chat`/`.list`
        methods) — application code should leave it unset so a real
        `ollama.Client` is built from `host`/`timeout`.

        `thinking_capability` pins the model's thinking behavior (tests, or
        a caller that already knows); left unset, it's read lazily from
        Ollama's `/api/show` on the first request via `show_fetcher` (a
        test seam; by default a plain HTTP call — the `ollama` package's
        own `show()` drops the `thinking` field this needs). Only a
        successful read is cached, so a request made while Ollama is down
        is retried next time instead of being stuck on UNKNOWN."""
        self._model = model
        self._host = host
        self._timeout = timeout
        self._keep_alive = keep_alive
        self._client = client if client is not None else ollama.Client(host=host, timeout=timeout)
        self._capability = thinking_capability
        self._show_fetcher = show_fetcher if show_fetcher is not None else self._fetch_show_payload
        self._capability_lock = threading.Lock()

    @property
    def name(self) -> str:
        return "ollama"

    def thinking_capability(self) -> ThinkingCapability:
        """The model's thinking behavior, probing Ollama once if needed."""
        with self._capability_lock:
            if self._capability is not None:
                return self._capability
            try:
                capability = parse_thinking_capability(self._show_fetcher())
            except Exception as exc:  # any failure: stay safe, retry next time
                logger.debug("Could not read model capabilities from Ollama", exc_info=exc)
                return ThinkingCapability.UNKNOWN
            logger.info("Model %s thinking capability: %s", self._model, capability.value)
            self._capability = capability
            return capability

    def _fetch_show_payload(self) -> dict[str, Any]:
        response = httpx.post(
            f"{self._host.rstrip('/')}/api/show", json={"model": self._model}, timeout=self._timeout
        )
        response.raise_for_status()
        return response.json()

    def _request_plan(self, reasoning_mode: ReasoningMode) -> tuple[bool | None, bool]:
        """(`think` to send, whether the output filter must assume reasoning
        may start with no opening tag)."""
        capability = self.thinking_capability()
        think = _think_param(capability, reasoning_mode)
        implicit_open = capability is ThinkingCapability.UNKNOWN and think is False
        return think, implicit_open

    def generate(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> ModelResponse:
        think, implicit_open = self._request_plan(reasoning_mode)
        try:
            response = self._client.chat(
                model=self._model,
                messages=_to_ollama_messages(messages),
                stream=False,
                think=think,
                keep_alive=self._keep_alive,
            )
        except _CONNECTION_ERRORS as exc:
            raise self._connection_error(exc) from exc
        except ollama.ResponseError as exc:
            raise self._response_error(exc) from exc
        except httpx.TimeoutException as exc:
            raise self._timeout_error(exc) from exc
        except Exception as exc:
            raise self._unexpected_error(exc) from exc

        # `response.message.thinking` (present when `think` is truthy) is
        # deliberately never read here — hidden reasoning text must never
        # reach ChatService/persistence, only the final visible content.
        # `content` itself still goes through the same reasoning filter the
        # streaming path uses: a model can put reasoning there too.
        output_filter = ReasoningOutputFilter(implicit_open=implicit_open)
        content = output_filter.feed(response.message.content or "") + output_filter.finish()
        self._log_filter_stats(output_filter)
        return ModelResponse(content=content, model_name=self._model)

    def stream(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> Iterator[str]:
        think, implicit_open = self._request_plan(reasoning_mode)
        output_filter = ReasoningOutputFilter(implicit_open=implicit_open)
        try:
            chunks = self._client.chat(
                model=self._model,
                messages=_to_ollama_messages(messages),
                stream=True,
                think=think,
                keep_alive=self._keep_alive,
            )
            for chunk in chunks:
                # As in `generate`, `chunk.message.thinking` is deliberately
                # never read/yielded — only user-visible content streams,
                # and only once the filter has released it as answer text.
                content = chunk.message.content
                visible = output_filter.feed(content) if content else ""
                # Yield even when nothing is visible yet (reasoning, or text
                # the filter is still holding back): "" is a progress signal
                # that lets the caller's thread service other work between
                # tokens — see `ModelProvider.stream`.
                yield visible
            tail = output_filter.finish()
            if tail:
                yield tail
            self._log_filter_stats(output_filter)
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
            # Counts only — never the reasoning or answer text itself.
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
