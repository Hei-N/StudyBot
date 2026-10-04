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


# Sentinel reasoning text: tests assert it never reaches any visible,
# persisted or re-sent surface.
REASONING_SENTINEL = "SECRET-REASONING-7f3a"


class FakeThinkingModelClient:
    """Imitates how Ollama serves a *thinking* Qwen3 model, decided per
    request by the `think` parameter — the Stage 6.3 leak, reproduced
    deterministically:

    * `think=True`: reasoning arrives in the separate `thinking` field,
      `content` holds only the answer (Ollama's structured separation).
    * `think=False` with `thinking_only=True` (Qwen3-4B-Thinking-2507): the
      model reasons anyway; its template pre-opened `<think>`, so `content`
      carries the reasoning, a bare `</think>` line, then the answer.
    * `think=False` with `thinking_only=False` (a hybrid model), or
      `think=None`: `content` is just the answer.
    * `inline_tags=True`: `content` wraps reasoning in an explicit
      `<think>…</think>` span regardless of `think`.

    Streams are split into `chunk_size`-character pieces (so tags are split
    across chunks), with empty chunks interleaved. `answer_for` builds the
    answer from the request messages, so tests can see what the model was
    given.
    """

    def __init__(
        self,
        *,
        thinking_only: bool = True,
        inline_tags: bool = False,
        chunk_size: int = 3,
        answer_for: Callable[[list[dict]], str] | None = None,
        reasoning: str = f"Okay, the user wants help. {REASONING_SENTINEL} Let me plan the reply.",
    ) -> None:
        self.thinking_only = thinking_only
        self.inline_tags = inline_tags
        self.chunk_size = chunk_size
        self.answer_for = answer_for or (lambda messages: "Here is the answer.")
        self.reasoning = reasoning
        self.chat_calls: list[dict] = []

    def _parts(self, messages, think) -> tuple[str, str]:
        """(content, thinking) for this request."""
        answer = self.answer_for(messages)
        if self.inline_tags:
            return f"<think>\n{self.reasoning}\n</think>\n\n{answer}", ""
        if think is True:
            return answer, self.reasoning
        if think is False and self.thinking_only:
            return f"{self.reasoning}\n</think>\n\n{answer}", ""
        return answer, ""

    def chat(self, model, messages, stream=False, think=None, keep_alive=None):
        self.chat_calls.append(
            {"model": model, "messages": messages, "stream": stream, "think": think, "keep_alive": keep_alive}
        )
        content, thinking = self._parts(messages, think)
        if not stream:
            return FakeChatResponse(content, thinking or None)
        return self._stream(content, thinking)

    def _stream(self, content: str, thinking: str) -> Iterator[FakeChatResponse]:
        size = self.chunk_size
        for i in range(0, len(thinking), size):
            yield FakeChatResponse("", thinking[i : i + size])
        for i in range(0, len(content), size):
            yield FakeChatResponse("")
            yield FakeChatResponse(content[i : i + size])

    def list(self):
        return FakeListResponse(["qwen3:4b"])
