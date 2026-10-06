import threading
import time

import httpx
import ollama
import pytest

from studybot.core.exceptions import ModelError
from studybot.core.messages import Message
from studybot.core.reasoning_mode import ReasoningMode
from studybot.models.base import ModelCapabilities
from studybot.models.ollama import OllamaModel, ThinkingCapability
from tests.fake_ollama import FakeChatResponse, FakeListResponse, FakeOllamaClient


def make_model(
    client: FakeOllamaClient,
    model: str = "qwen3:4b",
    capability: ThinkingCapability = ThinkingCapability.TOGGLEABLE,
) -> OllamaModel:
    # Capability is always pinned: a test must never probe a real Ollama.
    return OllamaModel(model=model, host="http://localhost:11434", client=client, thinking_capability=capability)


# --- message conversion -----------------------------------------------------


def test_generate_converts_roles_and_preserves_order():
    fake = FakeOllamaClient(chat_response=FakeChatResponse("hi there"))
    model = make_model(fake)
    messages = [
        Message.system("You are a bot."),
        Message.user("first"),
        Message.assistant("ack"),
        Message.user("second"),
    ]

    model.generate(messages)

    sent = fake.chat_calls[0]["messages"]
    assert sent == [
        {"role": "system", "content": "You are a bot."},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ack"},
        {"role": "user", "content": "second"},
    ]


def test_generate_uses_configured_model_name():
    fake = FakeOllamaClient(chat_response=FakeChatResponse("hi"))
    model = make_model(fake, model="gemma:2b")

    model.generate([Message.user("hi")])

    assert fake.chat_calls[0]["model"] == "gemma:2b"


def test_ollama_model_constructs_client_with_configured_host_and_timeout(monkeypatch):
    captured: dict = {}

    class DummyClient:
        def __init__(self, host=None, timeout=None):
            captured["host"] = host
            captured["timeout"] = timeout

    monkeypatch.setattr("studybot.models.ollama.ollama.Client", DummyClient)

    OllamaModel(model="qwen3:4b", host="http://example.local:9999", timeout=42.0)

    assert captured == {"host": "http://example.local:9999", "timeout": 42.0}


def test_constructing_ollama_model_does_not_touch_network(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("ollama.Client should not be constructed when a client is injected")

    monkeypatch.setattr("studybot.models.ollama.ollama.Client", fail_if_called)

    # Should not raise: no network/client construction happens because a
    # fake client is injected, and this constructor path never calls out.
    OllamaModel(model="qwen3:4b", client=FakeOllamaClient())


# --- response extraction -----------------------------------------------------


def test_generate_extracts_response_content():
    fake = FakeOllamaClient(chat_response=FakeChatResponse("The answer is 42."))
    model = make_model(fake)

    response = model.generate([Message.user("question")])

    assert response.content == "The answer is 42."
    assert response.model_name == "qwen3:4b"


def test_generate_never_returns_hidden_thinking_as_content():
    fake = FakeOllamaClient(chat_response=FakeChatResponse("42", thinking="let me reason about this..."))
    model = make_model(fake)

    response = model.generate([Message.user("question")], reasoning_mode=ReasoningMode.DEEP)

    assert response.content == "42"
    assert "reason" not in response.content


# --- reasoning mode -> think mapping ------------------------------------------


def test_generate_defaults_to_think_false_fast_mode():
    fake = FakeOllamaClient(chat_response=FakeChatResponse("hi"))
    model = make_model(fake)

    model.generate([Message.user("hi")])

    assert fake.chat_calls[0]["think"] is False


def test_generate_fast_reasoning_mode_maps_to_think_false():
    fake = FakeOllamaClient(chat_response=FakeChatResponse("hi"))
    model = make_model(fake)

    model.generate([Message.user("hi")], reasoning_mode=ReasoningMode.FAST)

    assert fake.chat_calls[0]["think"] is False


def test_generate_deep_reasoning_mode_maps_to_think_true():
    fake = FakeOllamaClient(chat_response=FakeChatResponse("hi"))
    model = make_model(fake)

    model.generate([Message.user("hi")], reasoning_mode=ReasoningMode.DEEP)

    assert fake.chat_calls[0]["think"] is True


def test_stream_fast_reasoning_mode_maps_to_think_false():
    def stream_factory():
        yield FakeChatResponse("hi")

    fake = FakeOllamaClient(stream_factory=stream_factory)
    model = make_model(fake)

    list(model.stream([Message.user("hi")], reasoning_mode=ReasoningMode.FAST))

    assert fake.chat_calls[0]["think"] is False


def test_stream_deep_reasoning_mode_maps_to_think_true():
    def stream_factory():
        yield FakeChatResponse("hi")

    fake = FakeOllamaClient(stream_factory=stream_factory)
    model = make_model(fake)

    list(model.stream([Message.user("hi")], reasoning_mode=ReasoningMode.DEEP))

    assert fake.chat_calls[0]["think"] is True


# --- streaming ---------------------------------------------------------------


def test_stream_yields_each_chunk_of_content():
    def stream_factory():
        yield FakeChatResponse("Hello")
        yield FakeChatResponse(" world")

    fake = FakeOllamaClient(stream_factory=stream_factory)
    model = make_model(fake)

    chunks = list(model.stream([Message.user("hi")]))

    assert chunks == ["Hello", " world"]


def test_stream_turns_empty_or_none_content_into_progress_signals():
    def stream_factory():
        yield FakeChatResponse("Hello")
        yield FakeChatResponse(None)
        yield FakeChatResponse("")
        yield FakeChatResponse(" world")

    fake = FakeOllamaClient(stream_factory=stream_factory)
    model = make_model(fake)

    chunks = list(model.stream([Message.user("hi")]))

    # One yield per Ollama chunk; chunks with no visible text become ""
    # progress signals (see ModelProvider.stream), never None.
    assert chunks == ["Hello", "", "", " world"]


def test_stream_never_yields_hidden_thinking_chunks():
    """Ollama's streaming chunks carry `thinking` and `content` as separate
    fields on the same message — a chunk that's *only* thinking (as real
    Qwen3 output looks like before the visible answer starts) must never
    leak into what this provider yields."""

    def stream_factory():
        yield FakeChatResponse(content=None, thinking="reasoning step one...")
        yield FakeChatResponse(content=None, thinking="reasoning step two...")
        yield FakeChatResponse(content="The answer is 42.")

    fake = FakeOllamaClient(stream_factory=stream_factory)
    model = make_model(fake)

    chunks = list(model.stream([Message.user("hi")], reasoning_mode=ReasoningMode.DEEP))

    # Thinking-only chunks surface as "" progress signals, never as text.
    assert chunks == ["", "", "The answer is 42."]
    assert not any("reasoning step" in c for c in chunks)


def test_stream_raises_model_error_partway_through():
    def stream_factory():
        yield FakeChatResponse("partial")
        raise ollama.ResponseError("boom", 500)

    fake = FakeOllamaClient(stream_factory=stream_factory)
    model = make_model(fake)

    received = []
    with pytest.raises(ModelError):
        for chunk in model.stream([Message.user("hi")]):
            received.append(chunk)

    assert received == ["partial"]


# --- error translation --------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [ConnectionError("Failed to connect to Ollama."), httpx.ConnectError("refused")],
)
def test_generate_raises_model_error_on_connection_failure(exc):
    fake = FakeOllamaClient(chat_exception=exc)
    model = make_model(fake)

    with pytest.raises(ModelError, match="Could not connect to the local Ollama service"):
        model.generate([Message.user("hi")])


@pytest.mark.parametrize(
    "exc",
    [ConnectionError("Failed to connect to Ollama."), httpx.ConnectError("refused")],
)
def test_stream_raises_model_error_on_connection_failure(exc):
    fake = FakeOllamaClient(chat_exception=exc)
    model = make_model(fake)

    with pytest.raises(ModelError, match="Could not connect to the local Ollama service"):
        list(model.stream([Message.user("hi")]))


def test_generate_raises_understandable_error_for_missing_model():
    fake = FakeOllamaClient(chat_exception=ollama.ResponseError("model 'qwen3:4b' not found", 404))
    model = make_model(fake)

    with pytest.raises(ModelError, match="not available locally") as excinfo:
        model.generate([Message.user("hi")])
    assert "ollama pull qwen3:4b" in str(excinfo.value)


def test_generate_raises_model_error_for_other_response_errors():
    fake = FakeOllamaClient(chat_exception=ollama.ResponseError("server exploded", 500))
    model = make_model(fake)

    with pytest.raises(ModelError):
        model.generate([Message.user("hi")])


def test_generate_raises_model_error_on_timeout():
    fake = FakeOllamaClient(chat_exception=httpx.ReadTimeout("too slow"))
    model = make_model(fake)

    with pytest.raises(ModelError, match="did not respond in time"):
        model.generate([Message.user("hi")])


def test_generate_wraps_unexpected_errors_as_model_error():
    fake = FakeOllamaClient(chat_exception=ValueError("something odd"))
    model = make_model(fake)

    with pytest.raises(ModelError):
        model.generate([Message.user("hi")])


# --- status --------------------------------------------------------------------


def test_status_when_server_reachable_and_model_available():
    fake = FakeOllamaClient(list_response=FakeListResponse(["qwen3:4b", "llama3:latest"]))
    model = make_model(fake, model="qwen3:4b")

    status = model.get_status()

    assert status.provider_name == "ollama"
    assert status.server_reachable is True
    assert status.model_name == "qwen3:4b"
    assert status.model_available is True


def test_status_normalizes_default_tag_when_checking_availability():
    fake = FakeOllamaClient(list_response=FakeListResponse(["llama3:latest"]))
    model = make_model(fake, model="llama3")

    status = model.get_status()

    assert status.model_available is True


def test_status_when_model_not_available():
    fake = FakeOllamaClient(list_response=FakeListResponse(["some-other-model:latest"]))
    model = make_model(fake, model="qwen3:4b")

    status = model.get_status()

    assert status.server_reachable is True
    assert status.model_available is False


@pytest.mark.parametrize(
    "exc",
    [ConnectionError("Failed to connect to Ollama."), httpx.ConnectError("refused")],
)
def test_status_when_server_unreachable(exc):
    fake = FakeOllamaClient(list_exception=exc)
    model = make_model(fake)

    status = model.get_status()

    assert status.server_reachable is False
    assert status.model_available is None
    assert status.detail is not None


def test_status_does_not_raise_on_unexpected_error():
    fake = FakeOllamaClient(list_exception=ValueError("weird"))
    model = make_model(fake)

    status = model.get_status()

    assert status.server_reachable is False
    assert status.model_available is None


# --- Stage 6.4: provider-neutral capabilities ---------------------------------------


def show_payload(
    capabilities=("completion", "tools", "thinking"),
    thinking_values=(True,),
    model_info=None,
):
    """A realistic `/api/show` payload; pass None to omit a field."""
    payload = {}
    if capabilities is not None:
        payload["capabilities"] = list(capabilities)
    if thinking_values is not None:
        payload["thinking"] = {"values": list(thinking_values), "default": True}
    if model_info is not None:
        payload["model_info"] = model_info
    return payload


def capability_model(payload, **kwargs):
    """An OllamaModel whose `/api/show` is a counting stub (never a network)."""
    calls = []

    def fetch():
        calls.append(1)
        if isinstance(payload, Exception):
            raise payload
        return payload

    model = OllamaModel(model="m", client=FakeOllamaClient(), show_fetcher=fetch, **kwargs)
    return model, calls


@pytest.mark.parametrize(
    ("capabilities", "vision", "tools"),
    [
        (["completion", "vision", "tools"], True, True),
        (["completion", "vision"], True, False),
        (["completion", "tools"], False, True),
        (["completion"], False, False),
        ([], False, False),
    ],
)
def test_vision_and_tools_follow_the_capabilities_list(capabilities, vision, tools):
    model, _ = capability_model(show_payload(capabilities=capabilities, thinking_values=None))
    result = model.get_capabilities()
    assert result.supports_vision is vision
    assert result.supports_tools is tools


@pytest.mark.parametrize("bad", [None, "vision", 7, {"vision": True}])
def test_malformed_or_missing_capabilities_list_gives_unknown_not_false(bad):
    payload = show_payload(capabilities=None, thinking_values=None)
    if bad is not None:
        payload["capabilities"] = bad
    result = capability_model(payload)[0].get_capabilities()
    assert result.supports_vision is None
    assert result.supports_tools is None
    assert result.supports_thinking is None
    assert result.reasoning_modes_distinct is None


@pytest.mark.parametrize(
    ("capabilities", "values", "classification", "thinking", "distinct"),
    [
        (["thinking"], [True], ThinkingCapability.ALWAYS_ON, True, False),
        (["thinking"], [True, False], ThinkingCapability.TOGGLEABLE, True, True),
        (["completion"], None, ThinkingCapability.NONE, False, False),
        (["thinking"], None, ThinkingCapability.UNKNOWN, None, None),
    ],
)
def test_thinking_classification_maps_to_neutral_flags(capabilities, values, classification, thinking, distinct):
    model, _ = capability_model(show_payload(capabilities=capabilities, thinking_values=values))
    result = model.get_capabilities()
    assert model.thinking_capability() is classification
    assert result.supports_thinking is thinking
    assert result.reasoning_modes_distinct is distinct


@pytest.mark.parametrize(
    ("model_info", "expected"),
    [
        ({"qwen3.context_length": 262144, "qwen3.block_count": 36}, 262144),
        ({"gemma3.context_length": 131072}, 131072),
        ({"a.context_length": 4096, "b.context_length": 8192}, 8192),  # maximum wins
        ({"qwen3.block_count": 36}, None),
        ({}, None),
        ({"x.context_length": 0}, None),
        ({"x.context_length": -5}, None),
        ({"x.context_length": "4096"}, None),
        ({"x.context_length": 4096.0}, None),
        ({"x.context_length": True}, None),
        ({"x.context_length": None, "y.context_length": 2048}, 2048),
        ({"context_length": 4096}, None),  # must be a `.context_length` suffix
        ({"x.context_length_scaling": 9999}, None),
    ],
)
def test_context_window_extraction(model_info, expected):
    model, _ = capability_model(show_payload(model_info=model_info))
    assert model.get_capabilities().context_window == expected


@pytest.mark.parametrize("bad", [None, [], "info", 3])
def test_malformed_model_info_gives_no_context_window(bad):
    payload = show_payload()
    payload["model_info"] = bad
    result = capability_model(payload)[0].get_capabilities()
    assert result.context_window is None
    assert result.supports_tools is True  # the rest of the payload is still used


def test_failed_show_request_returns_unknowns_safely():
    model, calls = capability_model(ConnectionError("down"))
    assert model.get_capabilities() == ModelCapabilities(None, None, None, None, None)
    assert model.thinking_capability() is ThinkingCapability.UNKNOWN
    assert len(calls) == 2  # nothing was cached from the failures


def test_non_dict_show_payload_is_treated_as_a_failed_lookup():
    model, _ = capability_model(["not", "a", "dict"])
    assert model.get_capabilities() == ModelCapabilities(None, None, None, None, None)


def test_failed_lookup_is_retried_and_success_is_then_cached():
    outcomes = [ConnectionError("down"), show_payload(capabilities=["vision", "thinking"], thinking_values=[True, False])]
    calls = []

    def fetch():
        calls.append(1)
        outcome = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    model = OllamaModel(model="m", client=FakeOllamaClient(), show_fetcher=fetch)

    assert model.get_capabilities().supports_vision is None  # first: failed
    second = model.get_capabilities()  # retried: succeeds
    assert second.supports_vision is True and second.reasoning_modes_distinct is True
    for _ in range(5):
        model.get_capabilities()
        model.thinking_capability()
    assert len(calls) == 2  # exactly one failure + one success, then cached


def test_capabilities_and_thinking_share_one_cached_fetch():
    model, calls = capability_model(show_payload(model_info={"m.context_length": 8192}))
    model.get_capabilities()
    model.thinking_capability()
    model.get_capabilities()
    assert len(calls) == 1


def test_concurrent_callers_cause_exactly_one_fetch():
    calls = []
    gate = threading.Event()

    def slow_fetch():
        calls.append(1)
        gate.wait(5)
        return show_payload(model_info={"m.context_length": 4096})

    model = OllamaModel(model="m", client=FakeOllamaClient(), show_fetcher=slow_fetch)
    results = []

    def worker(use_capabilities):
        results.append(model.get_capabilities() if use_capabilities else model.thinking_capability())

    threads = [threading.Thread(target=worker, args=(i % 2 == 0,)) for i in range(12)]
    for thread in threads:
        thread.start()
    time.sleep(0.2)  # let every thread reach the lock
    gate.set()
    for thread in threads:
        thread.join(5)

    assert not any(t.is_alive() for t in threads)  # no deadlock
    assert len(results) == 12
    assert len(calls) == 1


def test_lock_is_not_held_after_a_fetch_raises():
    model, _ = capability_model(RuntimeError("boom"))
    model.get_capabilities()
    done = []
    thread = threading.Thread(target=lambda: done.append(model.get_capabilities()))
    thread.start()
    thread.join(5)
    assert done  # a second call after a failure did not deadlock


def test_construction_performs_zero_network_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network access during construction")

    monkeypatch.setattr(httpx, "post", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    fetcher_calls = []
    client = FakeOllamaClient()

    OllamaModel(model="m", client=client, show_fetcher=lambda: fetcher_calls.append(1) or {})
    OllamaModel(model="m")  # builds a real ollama.Client, which must stay lazy

    assert fetcher_calls == []
    assert client.chat_calls == [] and client.list_call_count == 0


def test_default_fetcher_posts_to_api_show_with_the_model_tag(monkeypatch):
    seen = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return show_payload()

    def fake_post(url, json, timeout):
        seen.update(url=url, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr(httpx, "post", fake_post)
    model = OllamaModel(model="qwen3.5:4b", host="http://example.local:11434/", timeout=7.0)

    assert model.get_capabilities().supports_tools is True
    assert seen == {"url": "http://example.local:11434/api/show", "json": {"model": "qwen3.5:4b"}, "timeout": 7.0}


def test_pinned_thinking_capability_wins_but_metadata_still_fills_other_fields():
    payload = show_payload(
        capabilities=["vision", "tools", "thinking"], thinking_values=[True, False], model_info={"m.context_length": 8192}
    )
    model, calls = capability_model(payload, thinking_capability=ThinkingCapability.ALWAYS_ON)

    result = model.get_capabilities()

    assert model.thinking_capability() is ThinkingCapability.ALWAYS_ON  # not the payload's TOGGLEABLE
    assert result == ModelCapabilities(True, True, True, False, 8192)
    assert len(calls) == 1


def test_pinned_thinking_survives_a_failed_metadata_lookup():
    model, _ = capability_model(ConnectionError("down"), thinking_capability=ThinkingCapability.TOGGLEABLE)
    assert model.get_capabilities() == ModelCapabilities(None, None, True, True, None)


def test_pinned_thinking_never_triggers_a_lookup_for_reasoning_requests():
    def forbidden():
        raise AssertionError("must not probe")

    fake = FakeOllamaClient(chat_response=FakeChatResponse("hi"))
    model = OllamaModel(
        model="m", client=fake, show_fetcher=forbidden, thinking_capability=ThinkingCapability.TOGGLEABLE
    )
    model.generate([Message.user("x")], reasoning_mode=ReasoningMode.FAST)
    assert fake.chat_calls[0]["think"] is False


def test_get_capabilities_makes_no_chat_request():
    fake = FakeOllamaClient()
    model = OllamaModel(model="m", client=fake, show_fetcher=lambda: show_payload())
    model.get_capabilities()
    assert fake.chat_calls == []


def test_stage_6_3_reasoning_filtering_is_unaffected_by_the_metadata_refactor():
    def stream_factory():
        yield FakeChatResponse("<think>secret plan</thi")
        yield FakeChatResponse("nk>The ans")
        yield FakeChatResponse("wer is 4.")

    fake = FakeOllamaClient(
        stream_factory=stream_factory, chat_response=FakeChatResponse("<think>secret</think>Four.")
    )
    model, _ = capability_model(show_payload(thinking_values=[True, False]))
    model._client = fake

    streamed = "".join(model.stream([Message.user("x")], reasoning_mode=ReasoningMode.FAST))

    assert streamed == "The answer is 4."
    assert fake.chat_calls[0]["think"] is False  # TOGGLEABLE + Fast
    assert model.generate([Message.user("x")]).content == "Four."
