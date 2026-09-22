"""Ollama-backed model provider.

This is the only module in the application allowed to import `ollama` (or
its `httpx` transport) or know anything about its request/response shapes.
Everything else talks to the `ModelProvider` protocol.
"""

from __future__ import annotations

import logging
from typing import Iterator, Sequence

import httpx
import ollama

from studybot.core.exceptions import ModelError
from studybot.core.messages import Message, Role
from studybot.core.reasoning_mode import DEFAULT_REASONING_MODE, ReasoningMode
from studybot.models.base import ModelResponse, ProviderStatus

logger = logging.getLogger(__name__)

_ROLE_TO_OLLAMA = {
    Role.SYSTEM: "system",
    Role.USER: "user",
    Role.ASSISTANT: "assistant",
}

# The only place that knows Qwen/Ollama's `think` request parameter exists
# — ChatService/SessionService only ever pass a generic ReasoningMode.
_REASONING_MODE_TO_THINK = {
    ReasoningMode.FAST: False,
    ReasoningMode.DEEP: True,
}

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
    ) -> None:
        """`client` is an injection seam for tests (a fake with `.chat`/`.list`
        methods) — application code should leave it unset so a real
        `ollama.Client` is built from `host`/`timeout`."""
        self._model = model
        self._host = host
        self._keep_alive = keep_alive
        self._client = client if client is not None else ollama.Client(host=host, timeout=timeout)

    @property
    def name(self) -> str:
        return "ollama"

    def generate(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> ModelResponse:
        try:
            response = self._client.chat(
                model=self._model,
                messages=_to_ollama_messages(messages),
                stream=False,
                think=_REASONING_MODE_TO_THINK[reasoning_mode],
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
        content = response.message.content or ""
        return ModelResponse(content=content, model_name=self._model)

    def stream(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> Iterator[str]:
        try:
            chunks = self._client.chat(
                model=self._model,
                messages=_to_ollama_messages(messages),
                stream=True,
                think=_REASONING_MODE_TO_THINK[reasoning_mode],
                keep_alive=self._keep_alive,
            )
            for chunk in chunks:
                # As in `generate`, `chunk.message.thinking` is deliberately
                # never read/yielded — only user-visible content streams.
                content = chunk.message.content
                if content:
                    yield content
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
