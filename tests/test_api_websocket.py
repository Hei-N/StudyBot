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
    """Yields a fixed, ordered sequence of chunks — for testing ordering,
    aggregation, and history persistence without depending on real model
    output or timing."""

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
    """Yields one chunk, then raises — for model-failure tests."""

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
    """Yields one chunk, then blocks on an event — lets a test deterministically
    disconnect the client mid-stream before the rest is produced."""

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
    """Like `client`, but lets the test swap in a fake `ModelProvider`
    (`studybot.app.create_model` is monkeypatched for the app's lifetime)."""

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
    """Consume events until `message_completed`, raising immediately (never
    hanging) if an `error` event arrives instead — a test bug should fail
    loudly, not block forever waiting for an event that will never come."""
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
    # Both chats are created up front, before either is ever messaged —
    # this used to be exactly the sequence that broke (see Stage 5.8's
    # `test_creating_second_chat_does_not_break_sending_to_first` below,
    # the direct regression test for that bug). It's safe now: every chat
    # is a real persisted row from the moment POST returns, and each
    # `send_message` loads its own chat fresh by id.
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
    """Stage 5.8: every streaming event carries `chatId`, not just
    `message_started` — so a client juggling multiple chats/connections can
    always attribute an event to the right one without guessing."""
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


# --- Stage 5.8: stateless multi-chat regression --------------------------------------


def test_creating_second_chat_does_not_break_sending_to_first(client):
    """The exact real bug this stage exists to fix: create chat A, do NOT
    message it, create chat B, then send to A — A must not 404. On the old
    `_activate()`-based implementation this failed because creating B (an
    unpersisted, in-memory "pending" chat) silently evicted A's own
    unpersisted in-memory state before A ever got a database row."""
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
    """Every chat-specific operation works purely by id, in any order,
    without a preceding GET/open of any kind — proving there is no hidden
    "activate this chat first" requirement anywhere in the route layer."""
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

    # Now address A directly — none of the above should have any bearing on it.
    response = client.get(f"/api/v1/chats/{chat_a}", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["teachingMode"] == "teach"
    assert response.json()["reasoningMode"] == "fast"


def test_websocket_send_works_for_a_chat_created_after_another_was_already_opened(client):
    """A second WebSocket connection addressing a brand-new chat must work
    even while an earlier connection already exists/has been used for a
    different chat — no shared cursor between connections."""
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


# --- Stage 5.8: same-chat CHAT_BUSY -----------------------------------------------------
#
# CHAT_BUSY itself (the per-chat generation lock in `SessionService`) is
# covered deterministically at the service layer in
# `test_session_service.py` — both via manual generator interleaving and
# via real OS threads racing on the same lock. It is deliberately not
# re-tested end-to-end over two WebSocket connections here: this API's
# engine dispatches every call through one dedicated single-worker
# executor (see `api/engine.py`), so whether a second connection's request
# is even *submitted* while the first is mid-generation is a genuine race
# against that executor's queue and the test model's own timing, not a
# property of the busy-detection logic itself — a WS-level test for it
# would be flaky (or slow) by construction rather than a meaningful check.


def test_unknown_message_type_produces_validation_error_event(client):
    chat_id = _create_chat(client)
    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "not_a_real_type", "chat_id": chat_id, "content": "hi"})
        event = ws.receive_json()
        assert event["type"] == "error"
        assert event["code"] == "VALIDATION_ERROR"
