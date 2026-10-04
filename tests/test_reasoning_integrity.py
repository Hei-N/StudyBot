"""Stage 6.3: no model reasoning reaches any visible, persisted or re-sent
surface — for every teaching mode × reasoning mode, streaming and not.

Everything runs against `FakeThinkingModelClient` (tests/fake_ollama.py),
which reproduces how Ollama serves thinking Qwen3 models; no real Ollama
is involved.
"""

import logging
import threading
import time

import pytest
from fastapi.testclient import TestClient

import studybot.app as app_module
from studybot.api.server import create_app
from studybot.app import StudyBotApp
from studybot.config.settings import Settings
from studybot.core.exceptions import ModelError, UnsafeModelOutputError
from studybot.core.messages import Message, Role
from studybot.core.mode_prompts import get_mode_prompt
from studybot.core.reasoning_mode import ReasoningMode
from studybot.core.teaching_mode import TeachingMode
from studybot.models.ollama import OllamaModel, ThinkingCapability, parse_thinking_capability
from tests.fake_ollama import REASONING_SENTINEL, FakeChatResponse, FakeThinkingModelClient

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
MATRIX = [(t, r) for t in TeachingMode for r in ReasoningMode]


def answer_naming_mode(messages):
    """The fake's answer names the teaching mode it was instructed with, so
    tests can check instructions reached the model."""
    system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
    for mode in TeachingMode:
        if get_mode_prompt(mode) in system:
            return f"Answer in {mode.value} mode (turn {sum(m['role'] == 'user' for m in messages)})."
    return "Answer with no mode."


def make_model(client, capability=ThinkingCapability.ALWAYS_ON):
    return OllamaModel(model="qwen3:4b", client=client, thinking_capability=capability)


def assert_clean(text):
    assert REASONING_SENTINEL not in text
    assert "<think>" not in text
    assert "</think>" not in text


# --- capability detection ----------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"capabilities": ["completion", "thinking"], "thinking": {"values": [True], "default": True}},
         ThinkingCapability.ALWAYS_ON),
        ({"capabilities": ["completion", "thinking"], "thinking": {"values": [True, False]}},
         ThinkingCapability.TOGGLEABLE),
        ({"capabilities": ["completion", "tools"]}, ThinkingCapability.NONE),
        ({"capabilities": ["completion", "thinking"]}, ThinkingCapability.UNKNOWN),
        ({}, ThinkingCapability.UNKNOWN),
        ({"capabilities": ["thinking"], "thinking": {"values": "bogus"}}, ThinkingCapability.UNKNOWN),
    ],
)
def test_parse_thinking_capability(payload, expected):
    assert parse_thinking_capability(payload) is expected


@pytest.mark.parametrize(
    ("capability", "mode", "think"),
    [
        (ThinkingCapability.ALWAYS_ON, ReasoningMode.FAST, True),
        (ThinkingCapability.ALWAYS_ON, ReasoningMode.DEEP, True),
        (ThinkingCapability.TOGGLEABLE, ReasoningMode.FAST, False),
        (ThinkingCapability.TOGGLEABLE, ReasoningMode.DEEP, True),
        (ThinkingCapability.NONE, ReasoningMode.FAST, None),
        (ThinkingCapability.NONE, ReasoningMode.DEEP, None),
        (ThinkingCapability.UNKNOWN, ReasoningMode.FAST, False),
        (ThinkingCapability.UNKNOWN, ReasoningMode.DEEP, True),
    ],
)
def test_think_parameter_per_capability_and_mode(capability, mode, think):
    client = FakeThinkingModelClient(thinking_only=False)
    make_model(client, capability).generate([Message.user("hi")], reasoning_mode=mode)
    assert client.chat_calls[0]["think"] is think


def test_capability_is_probed_once_and_cached():
    calls = []

    def fetch():
        calls.append(1)
        return {"capabilities": ["thinking"], "thinking": {"values": [True]}}

    client = FakeThinkingModelClient()
    model = OllamaModel(model="qwen3:4b", client=client, show_fetcher=fetch)
    model.generate([Message.user("a")])
    list(model.stream([Message.user("b")]))
    assert len(calls) == 1
    assert [c["think"] for c in client.chat_calls] == [True, True]


def test_failed_probe_is_retried_and_falls_back_safely():
    attempts = []

    def fetch():
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("down")
        return {"capabilities": ["thinking"], "thinking": {"values": [True]}}

    client = FakeThinkingModelClient(thinking_only=True)
    model = OllamaModel(model="qwen3:4b", client=client, show_fetcher=fetch)
    # First request: UNKNOWN → legacy think=False, reasoning inline, still stripped.
    first = model.generate([Message.user("a")])
    assert client.chat_calls[0]["think"] is False
    assert_clean(first.content)
    model.generate([Message.user("b")])
    assert client.chat_calls[1]["think"] is True
    assert len(attempts) == 2


def test_pinned_capability_never_probes():
    def fetch():
        raise AssertionError("must not probe")

    model = OllamaModel(
        model="qwen3:4b",
        client=FakeThinkingModelClient(thinking_only=False),
        thinking_capability=ThinkingCapability.TOGGLEABLE,
        show_fetcher=fetch,
    )
    model.generate([Message.user("hi")])


# --- the original leak, reproduced at the provider boundary ---------------------------


@pytest.mark.parametrize("mode", list(ReasoningMode))
def test_thinking_only_model_answer_is_clean_in_both_modes(mode):
    client = FakeThinkingModelClient(thinking_only=True)
    model = make_model(client, ThinkingCapability.ALWAYS_ON)
    chunks = list(model.stream([Message.user("help me practice")], reasoning_mode=mode))
    assert "".join(chunks) == "Here is the answer."
    for chunk in chunks:
        assert_clean(chunk)
    assert model.generate([Message.user("x")], reasoning_mode=mode).content == "Here is the answer."


def test_legacy_fast_mapping_on_thinking_only_model_would_leak():
    """Documents the pre-6.3 root cause: think=False on a thinking-only
    model puts reasoning in `content`. With capability UNKNOWN the filter's
    implicit mode still recovers the answer."""
    client = FakeThinkingModelClient(thinking_only=True)
    raw = client.chat("qwen3:4b", [], stream=False, think=False).message.content
    assert REASONING_SENTINEL in raw
    model = make_model(FakeThinkingModelClient(thinking_only=True), ThinkingCapability.UNKNOWN)
    chunks = list(model.stream([Message.user("x")], reasoning_mode=ReasoningMode.FAST))
    assert "".join(chunks) == "Here is the answer."


def test_misreported_toggleable_model_leak_fails_closed_in_fast():
    """If a model claims to be toggleable but leaks untagged reasoning
    under think=False anyway, the tripwire fails the generation rather than
    let the rest stream on."""
    model = make_model(FakeThinkingModelClient(thinking_only=True), ThinkingCapability.TOGGLEABLE)
    with pytest.raises(UnsafeModelOutputError):
        list(model.stream([Message.user("x")], reasoning_mode=ReasoningMode.FAST))
    with pytest.raises(UnsafeModelOutputError):
        model.generate([Message.user("x")], reasoning_mode=ReasoningMode.FAST)


@pytest.mark.parametrize("capability", list(ThinkingCapability))
@pytest.mark.parametrize("mode", list(ReasoningMode))
def test_inline_tagged_reasoning_is_stripped_for_every_capability(capability, mode):
    model = make_model(FakeThinkingModelClient(inline_tags=True, chunk_size=1), capability)
    chunks = list(model.stream([Message.user("x")], reasoning_mode=mode))
    assert "".join(chunks) == "Here is the answer."
    assert model.generate([Message.user("x")], reasoning_mode=mode).content == "Here is the answer."


def test_thinking_field_is_never_yielded():
    client = FakeThinkingModelClient(thinking_only=True)
    chunks = list(make_model(client).stream([Message.user("x")], reasoning_mode=ReasoningMode.DEEP))
    assert all(REASONING_SENTINEL not in c for c in chunks)


def test_unsafe_output_error_is_not_wrapped_as_unexpected():
    model = make_model(FakeThinkingModelClient(thinking_only=True), ThinkingCapability.TOGGLEABLE)
    with pytest.raises(UnsafeModelOutputError) as info:
        list(model.stream([Message.user("x")]))
    assert "unexpectedly" not in str(info.value)


def test_provider_logs_no_content(caplog):
    caplog.set_level(logging.DEBUG)
    model = make_model(FakeThinkingModelClient(inline_tags=True))
    list(model.stream([Message.user("my private question")]))
    model.generate([Message.user("my private question")])
    for record in caplog.records:
        text = record.getMessage()
        assert REASONING_SENTINEL not in text
        assert "private question" not in text
        assert "Here is the answer" not in text


# --- full stack: API, WebSocket, persistence, history ---------------------------------


@pytest.fixture
def api(tmp_path, monkeypatch):
    """TestClient over a real app with a fake thinking model (capability
    ALWAYS_ON, as the real qwen3:4b reports)."""
    fake = FakeThinkingModelClient(thinking_only=True, answer_for=answer_naming_mode)
    monkeypatch.setattr(app_module, "create_model", lambda settings: make_model(fake))
    settings = Settings.from_env(env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)})
    with TestClient(create_app(settings=settings, token=TOKEN)) as client:
        client.fake = fake
        yield client


def new_chat(client, teaching, reasoning):
    chat_id = client.post("/api/v1/chats", json={}, headers=HEADERS).json()["id"]
    client.put(f"/api/v1/chats/{chat_id}/mode", json={"mode": teaching.value}, headers=HEADERS)
    client.put(f"/api/v1/chats/{chat_id}/reasoning-mode", json={"reasoningMode": reasoning.value}, headers=HEADERS)
    return chat_id


def ws_send(client, chat_id, content):
    """Returns (deltas, completed_event_or_None, error_event_or_None)."""
    deltas = []
    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "send_message", "chat_id": chat_id, "content": content})
        while True:
            event = ws.receive_json()
            if event["type"] == "delta":
                deltas.append(event["content"])
            elif event["type"] == "message_completed":
                return deltas, event, None
            elif event["type"] == "error":
                return deltas, None, event


def seed_messages(client, chat_id, *pairs):
    """Write raw messages straight to storage (as a pre-6.3 build would
    have), on the engine's own worker thread — SQLite connections are
    thread-bound."""
    engine = client.app.state.engine
    repository = engine.app.sessions._repository

    def write():
        for role, content in pairs:
            repository.append_message(chat_id, role, content)

    engine._executor.submit(write).result()


def messages_of(client, chat_id):
    return client.get(f"/api/v1/chats/{chat_id}/messages", headers=HEADERS).json()


@pytest.mark.parametrize(("teaching", "reasoning"), MATRIX, ids=lambda v: v.value)
def test_matrix_streaming_integrity(api, teaching, reasoning):
    chat_id = new_chat(api, teaching, reasoning)

    deltas, completed, error = ws_send(api, chat_id, "first question")
    assert error is None
    expected = f"Answer in {teaching.value} mode (turn 1)."
    for delta in deltas:
        assert_clean(delta)
    assert "".join(deltas) == expected
    assert completed["message"]["content"] == expected

    call = api.fake.chat_calls[-1]
    assert call["think"] is True  # thinking-only model: always separated
    assert get_mode_prompt(teaching) in call["messages"][0]["content"]

    # Second turn: restored history re-sent to the model is clean.
    deltas, completed, error = ws_send(api, chat_id, "follow-up")
    assert error is None
    assert completed["message"]["content"] == f"Answer in {teaching.value} mode (turn 2)."
    for message in api.fake.chat_calls[-1]["messages"]:
        assert_clean(message["content"])

    stored = messages_of(api, chat_id)
    assert [m["role"] for m in stored] == ["user", "assistant", "user", "assistant"]
    for message in stored:
        assert_clean(message["content"])


@pytest.mark.parametrize(("teaching", "reasoning"), MATRIX, ids=lambda v: v.value)
def test_matrix_non_streaming_integrity(tmp_path, monkeypatch, teaching, reasoning):
    fake = FakeThinkingModelClient(thinking_only=True, answer_for=answer_naming_mode)
    monkeypatch.setattr(app_module, "create_model", lambda settings: make_model(fake))
    settings = Settings.from_env(env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)})
    study_app = StudyBotApp(settings)
    try:
        sessions = study_app.sessions
        chat = sessions.create_chat()
        sessions.set_teaching_mode_for_chat(chat.id, teaching)
        sessions.set_reasoning_mode_for_chat(chat.id, reasoning)
        reply = sessions.send_to_chat(chat.id, "question")
        assert reply.content == f"Answer in {teaching.value} mode (turn 1)."
        sessions.send_to_chat(chat.id, "again")
        for message in sessions.get_chat_history(chat.id):
            assert_clean(message.content)
        for message in fake.chat_calls[-1]["messages"]:
            assert_clean(message["content"])
    finally:
        study_app.close()


@pytest.mark.parametrize("reasoning", list(ReasoningMode))
def test_original_eng303_practice_scenario(api, reasoning):
    """The reported failure: Practice mode, 'help me to work practice
    quizzes', then 'ok'."""
    course = api.post("/api/v1/courses", json={"name": "ENG303"}, headers=HEADERS).json()
    chat_id = new_chat(api, TeachingMode.PRACTICE, reasoning)
    api.put(f"/api/v1/chats/{chat_id}/course", json={"courseId": course["id"]}, headers=HEADERS)
    for text in ("help me to work practice quizzes", "ok"):
        deltas, completed, error = ws_send(api, chat_id, text)
        assert error is None
        assert_clean("".join(deltas))
        assert_clean(completed["message"]["content"])


def test_malformed_output_sends_error_and_persists_only_user_message(tmp_path, monkeypatch):
    fake = FakeThinkingModelClient(thinking_only=True)
    monkeypatch.setattr(
        app_module, "create_model", lambda settings: make_model(fake, ThinkingCapability.TOGGLEABLE)
    )
    settings = Settings.from_env(env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)})
    with TestClient(create_app(settings=settings, token=TOKEN)) as client:
        chat_id = new_chat(client, TeachingMode.TEACH, ReasoningMode.FAST)
        deltas, completed, error = ws_send(client, chat_id, "hello")
        assert completed is None
        assert error["code"] == "MODEL_ERROR"
        assert REASONING_SENTINEL not in error["message"]
        assert [m["role"] for m in messages_of(client, chat_id)] == ["user"]


def test_unterminated_span_mid_stream_fails_closed(tmp_path, monkeypatch):
    class Unterminated(FakeThinkingModelClient):
        def _parts(self, messages, think):
            return f"<think>{REASONING_SENTINEL} never closes", ""

    fake = Unterminated()
    monkeypatch.setattr(app_module, "create_model", lambda settings: make_model(fake))
    settings = Settings.from_env(env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)})
    with TestClient(create_app(settings=settings, token=TOKEN)) as client:
        chat_id = new_chat(client, TeachingMode.EXAM, ReasoningMode.DEEP)
        deltas, completed, error = ws_send(client, chat_id, "hello")
        assert deltas == []
        assert error["code"] == "MODEL_ERROR"
        assert [m["role"] for m in messages_of(client, chat_id)] == ["user"]


def test_contaminated_stored_reply_is_not_resent_but_storage_is_untouched(api):
    chat_id = new_chat(api, TeachingMode.TEACH, ReasoningMode.FAST)
    contaminated = f"Okay, {REASONING_SENTINEL} plan\n</think>\n\nOld answer."
    seed_messages(api, chat_id, (Role.USER, "old question"), (Role.ASSISTANT, contaminated))

    _, completed, error = ws_send(api, chat_id, "new question")
    assert error is None

    sent = api.fake.chat_calls[-1]["messages"]
    assert [m["content"] for m in sent if m["role"] == "assistant"] == ["Old answer."]
    assert messages_of(api, chat_id)[1]["content"] == contaminated  # storage unchanged


def test_ambiguous_stored_reply_is_resent_unchanged(api):
    chat_id = new_chat(api, TeachingMode.TEACH, ReasoningMode.FAST)
    ambiguous = "Talking about </think> in prose."
    seed_messages(api, chat_id, (Role.USER, "q"), (Role.ASSISTANT, ambiguous))
    ws_send(api, chat_id, "next")
    sent = api.fake.chat_calls[-1]["messages"]
    assert [m["content"] for m in sent if m["role"] == "assistant"] == [ambiguous]


def test_no_cross_chat_contamination(api):
    a = new_chat(api, TeachingMode.PRACTICE, ReasoningMode.FAST)
    b = new_chat(api, TeachingMode.QUICK, ReasoningMode.DEEP)
    ws_send(api, a, "question for A")
    ws_send(api, b, "question for B")
    ws_send(api, a, "second for A")
    sent_for_a = api.fake.chat_calls[-1]["messages"]
    assert all("for B" not in m["content"] for m in sent_for_a)
    assert get_mode_prompt(TeachingMode.PRACTICE) in sent_for_a[0]["content"]
    assert [m["content"] for m in messages_of(api, b)] == ["question for B", "Answer in quick mode (turn 1)."]


def test_unsafe_output_error_maps_to_model_error_for_callers():
    assert issubclass(UnsafeModelOutputError, ModelError)


# --- engine liveness during silent reasoning ------------------------------------------


class SlowThinkingClient(FakeThinkingModelClient):
    """Streams thinking-only chunks until `release` is set, then the answer
    — like a real thinking model's long, silent reasoning phase."""

    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def _stream(self, content, thinking):
        self.started.set()
        while not self.release.is_set():
            yield FakeChatResponse(None, "thinking...")
            time.sleep(0.01)
        yield FakeChatResponse("Visible answer.")


def test_health_stays_responsive_while_a_reply_is_reasoning(tmp_path, monkeypatch):
    """Regression (found in manual testing): with reasoning no longer leaking
    as visible chunks, a stream sat inside a single `next()` on the API's one
    engine thread for the whole reasoning phase, so `/health` (and every
    other request) timed out and the app showed "engine unavailable"."""
    fake = SlowThinkingClient()
    monkeypatch.setattr(app_module, "create_model", lambda settings: make_model(fake))
    settings = Settings.from_env(env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)})
    safety = threading.Timer(10, fake.release.set)  # never hang the suite
    safety.start()
    try:
        with TestClient(create_app(settings=settings, token=TOKEN)) as client:
            chat_id = new_chat(client, TeachingMode.TEACH, ReasoningMode.DEEP)
            outcome = {}
            sender = threading.Thread(target=lambda: outcome.update(result=ws_send(client, chat_id, "hi")))
            sender.start()
            assert fake.started.wait(5)

            begin = time.monotonic()
            health = client.get("/api/v1/health", headers=HEADERS)
            elapsed = time.monotonic() - begin
            chats = client.get("/api/v1/chats", headers=HEADERS)
            still_reasoning = not fake.release.is_set()

            fake.release.set()
            sender.join(10)
    finally:
        safety.cancel()

    assert still_reasoning
    assert health.status_code == 200 and chats.status_code == 200
    assert elapsed < 2
    deltas, completed, error = outcome["result"]
    assert error is None
    assert deltas == ["Visible answer."]  # progress signals are never sent as deltas
    assert completed["message"]["content"] == "Visible answer."
