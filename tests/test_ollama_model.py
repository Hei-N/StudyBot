import logging
import threading
import time

import httpx
import ollama
import pytest

from studybot.core.exceptions import (
    GenerationDeadlineExceededError,
    GenerationTokenLimitExceededError,
    ModelError,
    UnsafeModelOutputError,
)
from studybot.core.messages import Message
from studybot.core.reasoning_mode import ReasoningMode
from studybot.models.base import ModelCapabilities
from studybot.models.generation import (
    DEFAULT_GENERATION_BUDGET_POLICY,
    GenerationBudget,
    GenerationBudgetPolicy,
)
from studybot.models.ollama import OllamaModel, ThinkingCapability, _close_stream_safely, _merge_options
from tests.fake_ollama import (
    REASONING_SENTINEL,
    FakeChatResponse,
    FakeListResponse,
    FakeOllamaClient,
    FakeThinkingModelClient,
    TickingClock,
    TrackedStream,
    final,
    reasoning,
    visible,
)


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
    # generate() consumes the same streamed, filtered path as stream(), so it
        # returns exactly what stream() produced.
    assert model.generate([Message.user("x")]).content == streamed
    assert fake.chat_calls[1]["stream"] is True


# --- generation budgets --------------------------------------------------------------------

MODES = [ReasoningMode.FAST, ReasoningMode.DEEP]
EXPECTED_TOKENS = {ReasoningMode.FAST: 4096, ReasoningMode.DEEP: 6144}
EXPECTED_DEADLINE = {ReasoningMode.FAST: 120.0, ReasoningMode.DEEP: 300.0}


def budget_model(client, clock=None, *, capability=ThinkingCapability.TOGGLEABLE, policy=None, model="qwen3:4b"):
    return OllamaModel(
        model=model,
        client=client,
        thinking_capability=capability,
        generation_budget_policy=policy or DEFAULT_GENERATION_BUDGET_POLICY,
        clock=clock or TickingClock(),
    )


def stream_client(clock, items, **stream_kwargs):
    """A fake client whose every streamed request returns a fresh
    `TrackedStream` (kept in `.streams`)."""
    client = FakeOllamaClient(chat_response=FakeChatResponse(""))
    client.streams = []

    def factory():
        tracked = TrackedStream(clock, items, **stream_kwargs)
        client.streams.append(tracked)
        return tracked

    client._stream_factory = factory
    return client


# num_predict -----------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_stream_sends_the_mode_budget_as_num_predict(mode):
    client = FakeOllamaClient(stream_factory=lambda: iter([FakeChatResponse("hi", None, "stop")]))
    list(budget_model(client).stream([Message.user("x")], reasoning_mode=mode))
    assert client.chat_calls[0]["options"] == {"num_predict": EXPECTED_TOKENS[mode]}


@pytest.mark.parametrize("mode", MODES)
def test_generate_sends_the_same_num_predict(mode):
    client = FakeOllamaClient(chat_response=FakeChatResponse("hi", None, "stop"))
    budget_model(client).generate([Message.user("x")], reasoning_mode=mode)
    assert client.chat_calls[0]["options"] == {"num_predict": EXPECTED_TOKENS[mode]}


@pytest.mark.parametrize("mode", MODES)
def test_num_ctx_and_sampling_options_are_never_added(mode):
    client = FakeOllamaClient(chat_response=FakeChatResponse("hi", None, "stop"))
    budget_model(client).generate([Message.user("x")], reasoning_mode=mode)
    options = client.chat_calls[0]["options"]
    assert set(options) == {"num_predict"}
    for forbidden in ("num_ctx", "temperature", "top_p", "top_k"):
        assert forbidden not in options


def test_every_production_request_is_streamed_even_for_generate():
    client = FakeOllamaClient(chat_response=FakeChatResponse("hi", None, "stop"))
    budget_model(client).generate([Message.user("x")])
    assert client.chat_calls[0]["stream"] is True


def test_existing_options_are_preserved_and_the_budget_wins_for_num_predict():
    existing = {"temperature": 0.2, "num_predict": 1, "stop": ["x"]}
    merged = _merge_options(existing, GenerationBudget(2048, 120.0))
    assert merged == {"temperature": 0.2, "num_predict": 2048, "stop": ["x"]}


def test_merging_options_never_mutates_the_callers_dict():
    existing = {"temperature": 0.2, "num_predict": 1}
    snapshot = dict(existing)
    merged = _merge_options(existing, GenerationBudget(2048, 120.0))
    assert existing == snapshot
    assert merged is not existing


def test_merging_with_no_existing_options_yields_only_num_predict():
    assert _merge_options(None, GenerationBudget(7, 1.0)) == {"num_predict": 7}
    assert _merge_options({}, GenerationBudget(7, 1.0)) == {"num_predict": 7}


@pytest.mark.parametrize("model", ["qwen3:4b", "qwen3.5:4b", "gemma3:4b", "custom-finetune:1b"])
@pytest.mark.parametrize("mode", MODES)
def test_the_budget_depends_only_on_the_reasoning_mode_never_the_model(model, mode):
    client = FakeOllamaClient(chat_response=FakeChatResponse("hi", None, "stop"))
    budget_model(client, model=model).generate([Message.user("x")], reasoning_mode=mode)
    assert client.chat_calls[0]["options"]["num_predict"] == EXPECTED_TOKENS[mode]


def test_a_custom_policy_is_honoured():
    policy = GenerationBudgetPolicy(GenerationBudget(32, 2.0), GenerationBudget(64, 4.0))
    client = FakeOllamaClient(stream_factory=lambda: iter([FakeChatResponse("hi", None, "stop")]))
    model = budget_model(client, policy=policy)
    list(model.stream([Message.user("x")], reasoning_mode=ReasoningMode.FAST))
    list(model.stream([Message.user("x")], reasoning_mode=ReasoningMode.DEEP))
    assert [c["options"]["num_predict"] for c in client.chat_calls] == [32, 64]


def test_the_private_budget_selector_delegates_to_the_policy():
    policy = GenerationBudgetPolicy(GenerationBudget(5, 1.0), GenerationBudget(6, 2.0))
    model = budget_model(FakeOllamaClient(), policy=policy)
    assert model._generation_budget(ReasoningMode.FAST) is policy.fast
    assert model._generation_budget(ReasoningMode.DEEP) is policy.deep


def test_the_default_policy_is_used_when_none_is_given():
    model = OllamaModel(model="m", client=FakeOllamaClient(), thinking_capability=ThinkingCapability.NONE)
    assert model._generation_budget_policy is DEFAULT_GENERATION_BUDGET_POLICY


def test_budget_requests_do_not_change_capability_lookup_behaviour():
    calls = []

    def fetch():
        calls.append(1)
        return {"capabilities": ["thinking"], "thinking": {"values": [True, False]}}

    client = FakeOllamaClient(chat_response=FakeChatResponse("hi", None, "stop"))
    model = OllamaModel(model="m", client=client, show_fetcher=fetch)
    model.generate([Message.user("a")])
    model.generate([Message.user("b")], reasoning_mode=ReasoningMode.DEEP)
    assert len(calls) == 1  # still one cached lookup
    assert [c["think"] for c in client.chat_calls] == [False, True]


# deadline (deterministic: injected clock, never sleeping) ---------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_chunks_flow_until_the_deadline_then_the_generation_fails(mode):
    deadline = EXPECTED_DEADLINE[mode]
    clock = TickingClock()
    client = stream_client(
        clock,
        [visible("a", deadline * 0.25), visible("b", deadline * 0.25), visible("c", deadline * 0.5), visible("d")],
    )
    model = budget_model(client, clock)
    received = []

    with pytest.raises(GenerationDeadlineExceededError) as info:
        for chunk in model.stream([Message.user("x")], reasoning_mode=mode):
            received.append(chunk)

    assert received == ["a", "b"]  # the chunk that reached the deadline is never exposed
    assert info.value.deadline_seconds == deadline
    assert isinstance(info.value, ModelError)
    stream = client.streams[0]
    assert stream.consumed == 3  # "d" was never consumed
    assert stream.close_calls == 1


@pytest.mark.parametrize("mode", MODES)
def test_just_before_the_deadline_still_succeeds(mode):
    deadline = EXPECTED_DEADLINE[mode]
    clock = TickingClock()
    client = stream_client(clock, [visible("ok", deadline - 0.001), final("stop")])
    assert "".join(budget_model(client, clock).stream([Message.user("x")], reasoning_mode=mode)) == "ok"


def test_reaching_the_deadline_exactly_counts_as_exceeded():
    clock = TickingClock()
    client = stream_client(clock, [visible("ok", 120.0), final("stop")])
    with pytest.raises(GenerationDeadlineExceededError):
        list(budget_model(client, clock).stream([Message.user("x")], reasoning_mode=ReasoningMode.FAST))


def test_progress_chunks_do_not_reset_the_deadline():
    clock = TickingClock()
    client = stream_client(clock, [reasoning(50), reasoning(50), reasoning(50), visible("never", 1)])
    yielded = []
    with pytest.raises(GenerationDeadlineExceededError):
        for chunk in budget_model(client, clock).stream([Message.user("x")]):
            yielded.append(chunk)
    assert yielded == ["", ""]  # two progress signals, then the third chunk crossed 120 s
    assert all(c == "" for c in yielded)
    assert client.streams[0].consumed == 3


def test_a_stream_of_only_progress_signals_cannot_run_forever():
    clock = TickingClock()
    client = stream_client(clock, [reasoning(10)] * 10_000)
    with pytest.raises(GenerationDeadlineExceededError):
        for _ in budget_model(client, clock).stream([Message.user("x")]):
            pass
    assert client.streams[0].consumed == 12  # 12 x 10 s reaches 120 s


def test_receiving_visible_tokens_does_not_extend_the_deadline():
    clock = TickingClock()
    client = stream_client(clock, [visible("t", 30)] * 100)
    with pytest.raises(GenerationDeadlineExceededError):
        for _ in budget_model(client, clock).stream([Message.user("x")]):
            pass
    assert client.streams[0].consumed == 4  # 4 x 30 s = 120 s: a total limit, not an inactivity one


def test_the_deadline_also_bounds_generate():
    clock = TickingClock()
    client = stream_client(clock, [visible("a", 100), visible("b", 100), final("stop")])
    with pytest.raises(GenerationDeadlineExceededError):
        budget_model(client, clock).generate([Message.user("x")], reasoning_mode=ReasoningMode.FAST)
    assert client.streams[0].close_calls == 1


def test_fast_and_deep_have_different_deadlines_for_identical_timing():
    def run(mode):
        clock = TickingClock()
        client = stream_client(clock, [visible("a", 200), final("stop")])
        return "".join(budget_model(client, clock).stream([Message.user("x")], reasoning_mode=mode))

    with pytest.raises(GenerationDeadlineExceededError):
        run(ReasoningMode.FAST)  # 200 s > 120 s
    assert run(ReasoningMode.DEEP) == "a"  # 200 s < 300 s


def test_the_deadline_is_measured_from_the_start_of_each_generation():
    clock = TickingClock(start=1_000_000.0)  # any monotonic origin
    client = stream_client(clock, [visible("ok", 10), final("stop")])
    model = budget_model(client, clock)
    assert "".join(model.stream([Message.user("x")])) == "ok"
    clock.now += 5_000  # a long idle gap between requests must not count
    assert "".join(model.stream([Message.user("x")])) == "ok"


def test_nothing_visible_is_discarded_into_a_successful_response_on_deadline():
    clock = TickingClock()
    client = stream_client(clock, [visible("partial answer", 10), visible("more", 200)])
    with pytest.raises(GenerationDeadlineExceededError):
        budget_model(client, clock).generate([Message.user("x")])  # no ModelResponse is ever produced


def test_deadline_failure_logs_numbers_only(caplog):
    caplog.set_level(logging.DEBUG)
    clock = TickingClock()
    client = stream_client(
        clock, [visible("PRIVATE-ANSWER-TEXT", 10), (200.0, FakeChatResponse(None, REASONING_SENTINEL))]
    )
    with pytest.raises(GenerationDeadlineExceededError):
        list(budget_model(client, clock).stream([Message.user("PRIVATE-PROMPT-TEXT")]))
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "kind=deadline" in text and "mode=fast" in text and "max_generated_tokens=4096" in text
    assert "deadline_seconds=120" in text and "elapsed_ms=" in text and "visible_chars=" in text
    for secret in ("PRIVATE-ANSWER-TEXT", "PRIVATE-PROMPT-TEXT", REASONING_SENTINEL):
        assert secret not in text


def test_deadline_error_message_has_no_content():
    error = GenerationDeadlineExceededError(120.0, 130.5)
    assert "120" in str(error)
    assert error.elapsed_seconds == 130.5


# token limit (done_reason) ----------------------------------------------------------------------


def test_done_reason_length_after_visible_content_is_a_failure_not_a_response():
    clock = TickingClock()
    client = stream_client(clock, [visible("some partial text"), final("length")])
    model = budget_model(client, clock)
    received = []
    with pytest.raises(GenerationTokenLimitExceededError) as info:
        for chunk in model.stream([Message.user("x")], reasoning_mode=ReasoningMode.FAST):
            received.append(chunk)
    assert "".join(received) == "some partial text"  # streamed, but the stream then ends in an error
    assert info.value.max_generated_tokens == 4096
    assert isinstance(info.value, ModelError)
    assert client.streams[0].close_calls == 1


def test_done_reason_length_makes_generate_raise_instead_of_returning_truncated_text():
    clock = TickingClock()
    client = stream_client(clock, [visible("some partial text"), final("length")])
    with pytest.raises(GenerationTokenLimitExceededError):
        budget_model(client, clock).generate([Message.user("x")], reasoning_mode=ReasoningMode.DEEP)


def test_the_token_limit_error_reports_the_modes_configured_cap():
    for mode in MODES:
        clock = TickingClock()
        client = stream_client(clock, [visible("x"), final("length")])
        with pytest.raises(GenerationTokenLimitExceededError) as info:
            list(budget_model(client, clock).stream([Message.user("x")], reasoning_mode=mode))
        assert info.value.max_generated_tokens == EXPECTED_TOKENS[mode]


def test_length_after_only_hidden_reasoning_is_a_token_limit_not_an_empty_answer():
    """A model that spends its whole allowance reasoning (no visible content) is
    reported as a token limit, not an empty answer.
    """
    clock = TickingClock()
    client = stream_client(clock, [reasoning(), reasoning(), final("length")])
    with pytest.raises(GenerationTokenLimitExceededError):
        list(budget_model(client, clock).stream([Message.user("x")]))


def test_done_reason_stop_is_a_normal_success():
    clock = TickingClock()
    client = stream_client(clock, [visible("Hello "), visible("world"), final("stop")])
    model = budget_model(client, clock)
    assert "".join(model.stream([Message.user("x")])) == "Hello world"
    client = stream_client(clock, [visible("Hello world"), final("stop")])
    assert budget_model(client, clock).generate([Message.user("x")]).content == "Hello world"


def test_a_missing_done_reason_is_a_normal_success():
    clock = TickingClock()
    client = stream_client(clock, [visible("fine")])  # a client/fake that never sets done_reason
    assert "".join(budget_model(client, clock).stream([Message.user("x")])) == "fine"


def test_done_reason_on_the_same_chunk_as_the_last_text_is_honoured():
    clock = TickingClock()
    client = stream_client(clock, [(1.0, FakeChatResponse("tail", None, "length"))])
    with pytest.raises(GenerationTokenLimitExceededError):
        list(budget_model(client, clock).stream([Message.user("x")]))


def test_stop_with_no_visible_answer_is_still_the_integrity_failure():
    clock = TickingClock()
    client = stream_client(clock, [reasoning(), final("stop")])
    with pytest.raises(UnsafeModelOutputError):
        list(budget_model(client, clock).stream([Message.user("x")]))


def test_token_limit_failure_logs_numbers_only(caplog):
    caplog.set_level(logging.DEBUG)
    clock = TickingClock()
    client = stream_client(clock, [visible("PRIVATE-ANSWER-TEXT"), final("length")])
    with pytest.raises(GenerationTokenLimitExceededError):
        list(budget_model(client, clock).stream([Message.user("PRIVATE-PROMPT-TEXT")], reasoning_mode=ReasoningMode.DEEP))
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "kind=token_limit" in text and "mode=deep" in text and "max_generated_tokens=6144" in text
    assert "PRIVATE-ANSWER-TEXT" not in text and "PRIVATE-PROMPT-TEXT" not in text


# generate / stream parity -------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("chunk_size", [1, 3, 7, 1000])
@pytest.mark.parametrize("inline_tags", [False, True])
@pytest.mark.parametrize("capability", [ThinkingCapability.ALWAYS_ON, ThinkingCapability.TOGGLEABLE])
def test_generate_equals_the_concatenated_stream_for_identical_provider_output(
    mode, chunk_size, inline_tags, capability
):
    def run(use_stream):
        client = FakeThinkingModelClient(
            thinking_only=capability is ThinkingCapability.ALWAYS_ON,
            inline_tags=inline_tags,
            chunk_size=chunk_size,
            answer_for=lambda messages: "Line one.\n\nSecond `code` line with **markdown**.",
        )
        model = budget_model(client, capability=capability)
        if use_stream:
            return "".join(model.stream([Message.user("x")], reasoning_mode=mode))
        return model.generate([Message.user("x")], reasoning_mode=mode).content

    assert run(use_stream=True) == run(use_stream=False) == "Line one.\n\nSecond `code` line with **markdown**."


def test_generate_ignores_empty_progress_chunks():
    clock = TickingClock()
    client = stream_client(clock, [reasoning(), visible("A"), reasoning(), visible("B"), final("stop")])
    assert budget_model(client, clock).generate([Message.user("x")]).content == "AB"


def test_generate_and_stream_apply_the_same_token_and_deadline_policy():
    for use_stream in (True, False):
        clock = TickingClock()
        client = stream_client(clock, [visible("a"), final("length")])
        model = budget_model(client, clock)
        call = (lambda: list(model.stream([Message.user("x")]))) if use_stream else (lambda: model.generate([Message.user("x")]))
        with pytest.raises(GenerationTokenLimitExceededError):
            call()
        clock = TickingClock()
        client = stream_client(clock, [visible("a", 500)])
        model = budget_model(client, clock)
        call = (lambda: list(model.stream([Message.user("x")]))) if use_stream else (lambda: model.generate([Message.user("x")]))
        with pytest.raises(GenerationDeadlineExceededError):
            call()


# stream cleanup -----------------------------------------------------------------------------------


def test_the_stream_is_closed_after_a_normal_completion():
    clock = TickingClock()
    client = stream_client(clock, [visible("ok"), final("stop")])
    list(budget_model(client, clock).stream([Message.user("x")]))
    assert client.streams[0].close_calls == 1


def test_the_stream_is_closed_when_the_filter_fails_closed():
    clock = TickingClock()
    client = stream_client(clock, [visible("planning\n</think>\nanswer"), final("stop")])
    with pytest.raises(UnsafeModelOutputError):
        list(budget_model(client, clock, capability=ThinkingCapability.TOGGLEABLE).stream([Message.user("x")]))
    assert client.streams[0].close_calls == 1


def test_the_stream_is_closed_when_the_consumer_abandons_the_generator_early():
    clock = TickingClock()
    client = stream_client(clock, [visible("a"), visible("b"), visible("c"), final("stop")])
    generator = budget_model(client, clock).stream([Message.user("x")])
    assert next(generator) == "a"
    generator.close()
    assert client.streams[0].close_calls == 1
    assert client.streams[0].consumed == 1  # nothing further was pulled


def test_a_stream_without_a_close_method_is_handled_safely():
    clock = TickingClock()
    client = stream_client(clock, [visible("ok", 500)], has_close=False)
    with pytest.raises(GenerationDeadlineExceededError):
        list(budget_model(client, clock).stream([Message.user("x")]))
    client = stream_client(clock, [visible("ok"), final("stop")], has_close=False)
    assert "".join(budget_model(client, clock).stream([Message.user("x")])) == "ok"


def test_a_failing_close_never_masks_the_primary_error():
    clock = TickingClock()
    client = stream_client(clock, [visible("a"), final("length")], close_raises=True)
    with pytest.raises(GenerationTokenLimitExceededError):
        list(budget_model(client, clock).stream([Message.user("x")]))
    clock = TickingClock()
    client = stream_client(clock, [visible("a", 500)], close_raises=True)
    with pytest.raises(GenerationDeadlineExceededError):
        list(budget_model(client, clock).stream([Message.user("x")]))


def test_a_failing_close_after_success_does_not_fail_the_generation():
    clock = TickingClock()
    client = stream_client(clock, [visible("fine"), final("stop")], close_raises=True)
    assert "".join(budget_model(client, clock).stream([Message.user("x")])) == "fine"


def test_close_stream_safely_tolerates_odd_objects(caplog):
    _close_stream_safely(None)
    _close_stream_safely(object())

    class NotCallable:
        close = "nope"

    _close_stream_safely(NotCallable())

    class Boom:
        def close(self):
            raise RuntimeError("PRIVATE-DETAIL")

    caplog.set_level(logging.DEBUG)
    _close_stream_safely(Boom())
    assert "PRIVATE-DETAIL" not in "\n".join(r.getMessage() for r in caplog.records)


def test_connection_errors_still_translate_and_need_no_stream_to_close():
    model = budget_model(FakeOllamaClient(chat_exception=ConnectionError("down")))
    with pytest.raises(ModelError) as info:
        list(model.stream([Message.user("x")]))
    assert not isinstance(info.value, (GenerationDeadlineExceededError, GenerationTokenLimitExceededError))
