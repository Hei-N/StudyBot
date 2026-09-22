"""Fakes standing in for the `ollama` package's client boundary in tests.

These duck-type the two `ollama.Client` methods `OllamaModel` actually
calls (`chat`, `list`) so tests never touch a network or a real server.
"""

from __future__ import annotations

from typing import Callable, Iterator


class FakeMessage:
    def __init__(self, content: str | None, thinking: str | None = None) -> None:
        self.content = content
        self.thinking = thinking


class FakeChatResponse:
    def __init__(self, content: str | None, thinking: str | None = None) -> None:
        self.message = FakeMessage(content, thinking)


class FakeModelEntry:
    def __init__(self, model: str) -> None:
        self.model = model


class FakeListResponse:
    def __init__(self, model_names: list[str]) -> None:
        self.models = [FakeModelEntry(name) for name in model_names]


class FakeOllamaClient:
    """A stand-in for `ollama.Client`.

    Configure exactly one of `chat_response` / `stream_factory` /
    `chat_exception` depending on what the test needs `chat()` to do.
    """

    def __init__(
        self,
        *,
        chat_response: FakeChatResponse | None = None,
        stream_factory: Callable[[], Iterator[FakeChatResponse]] | None = None,
        chat_exception: Exception | None = None,
        list_response: FakeListResponse | None = None,
        list_exception: Exception | None = None,
    ) -> None:
        self._chat_response = chat_response
        self._stream_factory = stream_factory
        self._chat_exception = chat_exception
        self._list_response = list_response
        self._list_exception = list_exception
        self.chat_calls: list[dict] = []
        self.list_call_count = 0

    def chat(self, model, messages, stream=False, think=None, keep_alive=None):
        self.chat_calls.append(
            {"model": model, "messages": messages, "stream": stream, "think": think, "keep_alive": keep_alive}
        )
        if self._chat_exception is not None:
            raise self._chat_exception
        if stream:
            assert self._stream_factory is not None, "stream_factory not configured"
            return self._stream_factory()
        return self._chat_response

    def list(self):
        self.list_call_count += 1
        if self._list_exception is not None:
            raise self._list_exception
        return self._list_response
