import threading

import pytest
from fastapi.testclient import TestClient

import studybot.app as app_module
from studybot.api.server import create_app
from studybot.config.settings import Settings
from studybot.models.base import ModelResponse, ProviderStatus

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


class ChunkedModel:
    """Yields a fixed sequence of chunks, for testing ordering, aggregation and persistence."""

    name = "chunked"

    def __init__(self, chunks):
        self.chunks = chunks

    def generate(self, messages, *, reasoning_mode=None):
        raise AssertionError("not used in these tests")

    def stream(self, messages, *, reasoning_mode=None):
        yield from self.chunks

    def get_status(self):
        return ProviderStatus(
            provider_name=self.name, server_reachable=True, model_name=self.name, model_available=True
        )


class FailingStreamModel:
    """Yields one chunk, then raises; for model-failure tests."""

    name = "failing"

    def generate(self, messages, *, reasoning_mode=None):
        raise AssertionError("not used in these tests")

    def stream(self, messages, *, reasoning_mode=None):
        from studybot.core.exceptions import ModelError

        yield "partial "
        raise ModelError("the model exploded")

    def get_status(self):
        return ProviderStatus(
            provider_name=self.name, server_reachable=True, model_name=self.name, model_available=True
        )


class SlowStreamModel:
    """Yields one chunk, then blocks on an event, so a test can disconnect the client mid-stream.
    """

    name = "slow"

    def __init__(self, release_event, remaining_chunks):
        self._release_event = release_event
        self._remaining_chunks = remaining_chunks

    def generate(self, messages, *, reasoning_mode=None):
        raise AssertionError("not used in these tests")

    def stream(self, messages, *, reasoning_mode=None):
        yield "chunk1"
        if self._release_event.wait(timeout=5):
            yield from self._remaining_chunks

    def get_status(self):
        return ProviderStatus(
            provider_name=self.name, server_reachable=True, model_name=self.name, model_available=True
        )


@pytest.fixture
def client(tmp_path):
    settings = Settings.from_env(
        env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)}
    )
    app = create_app(settings=settings, token=TOKEN)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_with_model(tmp_path):
    """Like ``client``, but swaps in a fake ``ModelProvider`` (monkeypatches
    ``studybot.app.create_model`` for the app's lifetime).
    """

    def _make(model_factory):
        original = app_module.create_model
        app_module.create_model = lambda settings: model_factory()
        settings = Settings.from_env(
            env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)}
        )
        app = create_app(settings=settings, token=TOKEN)
        return app, original

    created = []

    def factory(model_factory):
        app, original = _make(model_factory)
        created.append(original)
        return app

    yield factory

    if created:
        app_module.create_model = created[-1]


def _create_chat(client) -> str:
    return client.post("/api/v1/chats", json={}, headers=HEADERS).json()["id"]


def _drain_until_completed(ws) -> dict:
    """Consume events until ``message_completed``; fail immediately on an ``error`` event instead of hanging.
    """
    while True:
        event = ws.receive_json()
        if event["type"] == "message_completed":
            return event
        if event["type"] == "error":
            raise AssertionError(f"unexpected error event: {event}")


def test_stream_events_arrive_in_order(client):
    chat_id = _create_chat(client)

    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "send_message", "chat_id": chat_id, "content": "hello"})
        types = []
        while True:
            event = ws.receive_json()
            types.append(event["type"])
            if event["type"] in ("message_completed", "error"):
                break

    assert types[0] == "message_started"
    assert types[-1] == "message_completed"
    assert all(t == "delta" for t in types[1:-1])
    assert len(types) >= 3  # started, at least one delta, completed


def test_multiple_deltas_aggregate_into_the_full_message(client_with_model):
    app = client_with_model(lambda: ChunkedModel(["Hello", ", ", "world", "!"]))
    with TestClient(app) as client:
        chat_id = _create_chat(client)
        with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
            ws.send_json({"type": "send_message", "chat_id": chat_id, "content": "hi"})
            deltas = []
            completed = None
            while completed is None:
                event = ws.receive_json()
                if event["type"] == "delta":
                    deltas.append(event["content"])
                elif event["type"] == "message_completed":
                    completed = event

        assert deltas == ["Hello", ", ", "world", "!"]
        assert completed["message"]["content"] == "Hello, world!"


def test_one_complete_assistant_message_is_persisted(client_with_model):
    app = client_with_model(lambda: ChunkedModel(["a", "b", "c"]))
    with TestClient(app) as client:
        chat_id = _create_chat(client)
        with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
            ws.send_json({"type": "send_message", "chat_id": chat_id, "content": "hi"})
            _drain_until_completed(ws)

        messages = client.get(f"/api/v1/chats/{chat_id}/messages", headers=HEADERS).json()
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert messages[1]["content"] == "abc"


def test_model_failure_produces_error_event(client_with_model):
    app = client_with_model(FailingStreamModel)
    with TestClient(app) as client:
        chat_id = _create_chat(client)
        with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
            ws.send_json({"type": "send_message", "chat_id": chat_id, "content": "hi"})
            events = []
            while True:
                event = ws.receive_json()
                events.append(event)
                if event["type"] in ("message_completed", "error"):
                    break

        assert events[-1]["type"] == "error"
        assert events[-1]["code"] == "MODEL_ERROR"


def test_failed_stream_does_not_persist_partial_assistant_message(client_with_model):
    app = client_with_model(FailingStreamModel)
    with TestClient(app) as client:
        chat_id = _create_chat(client)
        with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
            ws.send_json({"type": "send_message", "chat_id": chat_id, "content": "hi"})
            while True:
                event = ws.receive_json()
                if event["type"] in ("message_completed", "error"):
                    break

        messages = client.get(f"/api/v1/chats/{chat_id}/messages", headers=HEADERS).json()
        assert [m["role"] for m in messages] == ["user"]


def test_disconnect_mid_stream_does_not_persist_incomplete_response(client_with_model):
    release_event = threading.Event()
    app = client_with_model(lambda: SlowStreamModel(release_event, ["chunk2"]))
    with TestClient(app) as client:
        chat_id = _create_chat(client)

        with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
            ws.send_json({"type": "send_message", "chat_id": chat_id, "content": "hi"})
            assert ws.receive_json()["type"] == "message_started"
            assert ws.receive_json() == {"type": "delta", "content": "chunk1", "chatId": chat_id}
            # Exiting the `with` block here disconnects the client while the
            # model is still "generating" (blocked on release_event).

        # Let the model finish producing its remaining output; the server
        # should fail to deliver it (client gone) without crashing.
        release_event.set()

        import time

        time.sleep(0.3)

        messages = client.get(f"/api/v1/chats/{chat_id}/messages", headers=HEADERS).json()
        assert [m["role"] for m in messages] == ["user"]


def test_unknown_chat_id_produces_error_event_without_closing_connection(client):
    chat_id = _create_chat(client)

    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "send_message", "chat_id": "does-not-exist", "content": "hi"})
        error_event = ws.receive_json()
        assert error_event == {
            "type": "error",
            "code": "CHAT_NOT_FOUND",
            "message": "No chat found with id 'does-not-exist'.",
            "chatId": "does-not-exist",
        }

        # The connection is still usable afterward.
        ws.send_json({"type": "send_message", "chat_id": chat_id, "content": "hello"})
        _drain_until_completed(ws)


def test_unauthenticated_connection_is_rejected(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v1/ws/chat") as ws:
            ws.receive_json()


def test_histories_remain_isolated_between_chat_ids(client):
    # Both chats are created before either is messaged; each send_message loads
    # its own chat by id.
    chat_a = _create_chat(client)
    chat_b = _create_chat(client)

    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "send_message", "chat_id": chat_a, "content": "Remember ALPHA=1"})
        _drain_until_completed(ws)
        ws.send_json({"type": "send_message", "chat_id": chat_b, "content": "Remember BETA=2"})
        _drain_until_completed(ws)

    messages_a = client.get(f"/api/v1/chats/{chat_a}/messages", headers=HEADERS).json()
    messages_b = client.get(f"/api/v1/chats/{chat_b}/messages", headers=HEADERS).json()

    assert [m["content"] for m in messages_a] == [
        "Remember ALPHA=1",
        "[Mock] You said: Remember ALPHA=1",
    ]
    assert [m["content"] for m in messages_b] == [
        "Remember BETA=2",
        "[Mock] You said: Remember BETA=2",
    ]


def test_invalid_payload_produces_validation_error_event(client):
    chat_id = _create_chat(client)
    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "send_message", "chat_id": chat_id, "content": ""})
        event = ws.receive_json()
        assert event["type"] == "error"
        assert event["code"] == "VALIDATION_ERROR"


def test_delta_and_message_completed_events_carry_the_chat_id(client_with_model):
    """Every streaming event carries ``chatId``, so a client juggling several chats can attribute each event.
    """
    app = client_with_model(lambda: ChunkedModel(["hi"]))
    with TestClient(app) as client:
        chat_id = _create_chat(client)
        with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
            ws.send_json({"type": "send_message", "chat_id": chat_id, "content": "hi"})
            started = ws.receive_json()
            delta = ws.receive_json()
            completed = ws.receive_json()

    assert started["chatId"] == chat_id
    assert delta["chatId"] == chat_id
    assert completed["chatId"] == chat_id


# --- stateless multi-chat regression -------------------------------------------------


def test_creating_second_chat_does_not_break_sending_to_first(client):
    """Regression: creating chat B before A was messaged used to evict A's unpersisted state, so sending to A returned 404.
    """
    chat_a = _create_chat(client)
    chat_b = _create_chat(client)

    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "send_message", "chat_id": chat_a, "content": "Remember ALPHA = 17"})
        completed_a = _drain_until_completed(ws)

        ws.send_json({"type": "send_message", "chat_id": chat_b, "content": "Remember BETA = 84"})
        completed_b = _drain_until_completed(ws)

    assert completed_a["message"]["content"] == "[Mock] You said: Remember ALPHA = 17"
    assert completed_b["message"]["content"] == "[Mock] You said: Remember BETA = 84"

    messages_a = client.get(f"/api/v1/chats/{chat_a}/messages", headers=HEADERS).json()
    messages_b = client.get(f"/api/v1/chats/{chat_b}/messages", headers=HEADERS).json()
    assert [m["content"] for m in messages_a] == ["Remember ALPHA = 17", "[Mock] You said: Remember ALPHA = 17"]
    assert [m["content"] for m in messages_b] == ["Remember BETA = 84", "[Mock] You said: Remember BETA = 84"]


def test_api_never_requires_opening_a_chat_before_addressing_it(client):
    """Every chat operation works by id alone, in any order, with no 'open' step."""
    chat_a = _create_chat(client)
    chat_b = _create_chat(client)

    # Touch B first via several different explicit operations, all before A
    # has ever been addressed at all.
    assert client.put(f"/api/v1/chats/{chat_b}/mode", json={"mode": "exam"}, headers=HEADERS).status_code == 200
    assert (
        client.put(f"/api/v1/chats/{chat_b}/reasoning-mode", json={"reasoningMode": "deep"}, headers=HEADERS).status_code
        == 200
    )
    assert client.put(f"/api/v1/chats/{chat_b}/rename", json={"title": "B"}, headers=HEADERS).status_code == 200

    # Now address A directly; none of the above should have any bearing on it.
    response = client.get(f"/api/v1/chats/{chat_a}", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["teachingMode"] == "teach"
    assert response.json()["reasoningMode"] == "fast"


def test_websocket_send_works_for_a_chat_created_after_another_was_already_opened(client):
    """A second connection can address a brand-new chat while an earlier connection exists; there is no shared cursor.
    """
    chat_a = _create_chat(client)
    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws_a:
        ws_a.send_json({"type": "send_message", "chat_id": chat_a, "content": "hello a"})
        _drain_until_completed(ws_a)

        chat_b = _create_chat(client)  # created *during* connection A's lifetime
        with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws_b:
            ws_b.send_json({"type": "send_message", "chat_id": chat_b, "content": "hello b"})
            _drain_until_completed(ws_b)

        # Connection A still works for chat A afterward.
        ws_a.send_json({"type": "send_message", "chat_id": chat_a, "content": "hello a again"})
        _drain_until_completed(ws_a)

    messages_a = client.get(f"/api/v1/chats/{chat_a}/messages", headers=HEADERS).json()
    messages_b = client.get(f"/api/v1/chats/{chat_b}/messages", headers=HEADERS).json()
    assert [m["content"] for m in messages_a] == [
        "hello a",
        "[Mock] You said: hello a",
        "hello a again",
        "[Mock] You said: hello a again",
    ]
    assert [m["content"] for m in messages_b] == ["hello b", "[Mock] You said: hello b"]


# --- same-chat CHAT_BUSY -----------------------------------------------------------
# CHAT_BUSY is covered at the service layer in test_session_service.py (generator
# interleaving and real threads). It is not re-tested over two WebSocket
# connections: whether the second request is submitted mid-generation is a race
# against the single-worker executor, so such a test would be flaky by design.


def test_unknown_message_type_produces_validation_error_event(client):
    chat_id = _create_chat(client)
    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "not_a_real_type", "chat_id": chat_id, "content": "hi"})
        event = ws.receive_json()
        assert event["type"] == "error"
        assert event["code"] == "VALIDATION_ERROR"


# --- generation budget failures through the real provider ----------------------------

from tests.fake_ollama import REASONING_SENTINEL, flaky_budget_model


def _send_and_collect(client, chat_id, content):
    """All events for one send, up to and including message_completed/error."""
    events = []
    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "send_message", "chat_id": chat_id, "content": content})
        while True:
            event = ws.receive_json()
            events.append(event)
            if event["type"] in ("message_completed", "error"):
                return events


def _roles_and_contents(client, chat_id):
    messages = client.get(f"/api/v1/chats/{chat_id}/messages", headers=HEADERS).json()
    return [(m["role"], m["content"]) for m in messages]


@pytest.mark.parametrize("kind", ["deadline", "token_limit"])
def test_budget_failure_sends_model_error_and_never_message_completed(client_with_model, kind):
    model, streams = flaky_budget_model(kind)
    app = client_with_model(lambda: model)
    with TestClient(app) as client:
        chat_id = _create_chat(client)

        events = _send_and_collect(client, chat_id, "hello")

        assert events[0]["type"] == "message_started"
        assert events[-1]["type"] == "error" and events[-1]["code"] == "MODEL_ERROR"
        assert events[-1]["chatId"] == chat_id
        assert all(e["type"] != "message_completed" for e in events)
        assert REASONING_SENTINEL not in events[-1]["message"]
        assert "partial text" not in events[-1]["message"]  # numbers only: no answer text in the error
        assert streams[0].close_calls == 1


@pytest.mark.parametrize("kind", ["deadline", "token_limit"])
def test_budget_failure_persists_only_the_user_message_once(client_with_model, kind):
    model, _ = flaky_budget_model(kind)
    app = client_with_model(lambda: model)
    with TestClient(app) as client:
        chat_id = _create_chat(client)

        _send_and_collect(client, chat_id, "hello")

        assert _roles_and_contents(client, chat_id) == [("user", "hello")]


@pytest.mark.parametrize("kind", ["deadline", "token_limit"])
def test_the_partial_text_streamed_before_a_budget_failure_is_never_persisted(client_with_model, kind):
    model, _ = flaky_budget_model(kind)
    app = client_with_model(lambda: model)
    with TestClient(app) as client:
        chat_id = _create_chat(client)

        events = _send_and_collect(client, chat_id, "hello")

        deltas = [e["content"] for e in events if e["type"] == "delta"]
        assert deltas == ["partial text"]  # clients see it, then the error tells them to discard it
        assert all("partial text" not in content for _, content in _roles_and_contents(client, chat_id))


@pytest.mark.parametrize("kind", ["deadline", "token_limit"])
def test_engine_recovers_after_a_budget_failure(client_with_model, kind):
    model, streams = flaky_budget_model(kind)
    app = client_with_model(lambda: model)
    with TestClient(app) as client:
        chat_a, chat_b = _create_chat(client), _create_chat(client)

        failed = _send_and_collect(client, chat_a, "first")
        health = client.get("/api/v1/health", headers=HEADERS)
        retried = _send_and_collect(client, chat_a, "retry")  # same chat: its lock must be free
        other = _send_and_collect(client, chat_b, "other chat")

        assert failed[-1]["type"] == "error"
        assert health.status_code == 200 and health.json()["status"] == "ok"
        assert retried[-1]["type"] == "message_completed"
        assert retried[-1]["message"]["content"] == "A good answer."
        assert other[-1]["type"] == "message_completed"
        assert all(e.get("code") != "CHAT_BUSY" for e in retried + other)
        assert _roles_and_contents(client, chat_a) == [
            ("user", "first"),
            ("user", "retry"),
            ("assistant", "A good answer."),
        ]
        assert _roles_and_contents(client, chat_b) == [("user", "other chat"), ("assistant", "A good answer.")]
        assert all(stream.close_calls == 1 for stream in streams)  # no stream left dangling


@pytest.mark.parametrize("kind", ["deadline", "token_limit"])
def test_empty_progress_signals_never_reach_the_websocket_or_storage(client_with_model, kind):
    model, _ = flaky_budget_model(kind)
    app = client_with_model(lambda: model)
    with TestClient(app) as client:
        chat_id = _create_chat(client)
        _send_and_collect(client, chat_id, "first")

        events = _send_and_collect(client, chat_id, "second")

        assert all(e["content"] != "" for e in events if e["type"] == "delta")
        assert all(content != "" for _, content in _roles_and_contents(client, chat_id))
