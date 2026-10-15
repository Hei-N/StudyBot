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
    def __init__(
        self, content: str | None, thinking: str | None = None, done_reason: str | None = None
    ) -> None:
        self.message = FakeMessage(content, thinking)
        # Ollama sets `done_reason` ("stop" / "length") only on the final chunk.
        self.done_reason = done_reason
        self.done = done_reason is not None


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

    def chat(self, model, messages, stream=False, think=None, keep_alive=None, options=None):
        self.chat_calls.append(
            {
                "model": model,
                "messages": messages,
                "stream": stream,
                "think": think,
                "keep_alive": keep_alive,
                "options": options,
            }
        )
        if self._chat_exception is not None:
            raise self._chat_exception
        if stream:
            if self._stream_factory is not None:
                return self._stream_factory()
            # Production always streams, so a whole response becomes one chunk.
            assert self._chat_response is not None, "neither stream_factory nor chat_response configured"
            return iter([self._chat_response])
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

    def chat(self, model, messages, stream=False, think=None, keep_alive=None, options=None):
        self.chat_calls.append(
            {
                "model": model,
                "messages": messages,
                "stream": stream,
                "think": think,
                "keep_alive": keep_alive,
                "options": options,
            }
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


# --- deterministic time and stream tracking ----------------------------------------------


class TickingClock:
    """A monotonic clock that tests advance explicitly; no sleeping."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class TrackedStream:
    """A streamed response whose chunks advance a ``TickingClock`` as they are
    received, recording how many were consumed and how often it was closed.

    ``items`` is a sequence of ``(seconds_before_chunk, FakeChatResponse)``. Pass
    ``has_close=False`` to model an iterator with no ``close()``.
    """

    def __init__(self, clock: TickingClock, items, *, has_close: bool = True, close_raises: bool = False):
        self._clock = clock
        self._items = list(items)
        self.consumed = 0
        self.close_calls = 0
        self._close_raises = close_raises
        if not has_close:
            self.close = None  # type: ignore[assignment]  # shadows the method: getattr(..., "close") is not callable

    def __iter__(self):
        return self

    def __next__(self):
        if self.consumed >= len(self._items):
            raise StopIteration
        seconds, response = self._items[self.consumed]
        self.consumed += 1
        self._clock.now += seconds
        return response

    def close(self):
        self.close_calls += 1
        if self._close_raises:
            raise RuntimeError("close failed")


def visible(text: str, seconds: float = 1.0):
    """One scripted visible-content chunk."""
    return (seconds, FakeChatResponse(text))


def reasoning(seconds: float = 1.0):
    """One scripted hidden-thinking chunk (no visible content)."""
    return (seconds, FakeChatResponse(None, "SECRET-REASONING-7f3a"))


def final(done_reason: str, seconds: float = 0.0, content: str = ""):
    """The terminal chunk carrying Ollama's `done_reason`."""
    return (seconds, FakeChatResponse(content, None, done_reason))


def flaky_budget_model(kind: str):
    """A real ``OllamaModel`` (fake client and clock) whose first generation fails by
    budget (``kind`` is "deadline" or "token_limit") and whose later generations
    succeed.

    Returns ``(model, streams)``; ``streams`` collects every ``TrackedStream`` so
    tests can check each was closed. The failing generation first streams "partial
    text", to verify an incomplete answer is never persisted.
    """
    from studybot.models.ollama import OllamaModel, ThinkingCapability

    assert kind in ("deadline", "token_limit")
    clock = TickingClock()
    streams: list[TrackedStream] = []
    requests = {"n": 0}

    def factory():
        requests["n"] += 1
        if requests["n"] == 1:
            items = (
                [visible("partial text", 1.0), visible("never delivered", 500.0)]
                if kind == "deadline"
                else [visible("partial text", 1.0), final("length")]
            )
        else:
            items = [visible("A good answer.", 1.0), final("stop")]
        tracked = TrackedStream(clock, items)
        streams.append(tracked)
        return tracked

    client = FakeOllamaClient(stream_factory=factory, list_response=FakeListResponse(["m"]))
    model = OllamaModel(
        model="m", client=client, thinking_capability=ThinkingCapability.TOGGLEABLE, clock=clock
    )
    return model, streams
