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

    def generate(self, messages):
        raise AssertionError("not used in these tests")

    def stream(self, messages):
        yield from self.chunks

    def get_status(self):
        return ProviderStatus(
            provider_name=self.name, server_reachable=True, model_name=self.name, model_available=True
        )


class FailingStreamModel:
    """Yields one chunk, then raises — for model-failure tests."""

    name = "failing"

    def generate(self, messages):
        raise AssertionError("not used in these tests")

    def stream(self, messages):
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

    def generate(self, messages):
        raise AssertionError("not used in these tests")

    def stream(self, messages):
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
            assert ws.receive_json() == {"type": "delta", "content": "chunk1"}
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
        }

        # The connection is still usable afterward.
        ws.send_json({"type": "send_message", "chat_id": chat_id, "content": "hello"})
        _drain_until_completed(ws)


def test_unauthenticated_connection_is_rejected(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v1/ws/chat") as ws:
            ws.receive_json()


def test_histories_remain_isolated_between_chat_ids(client):
    # chat_a is created *and sent its first message* (so it's actually
    # persisted) before chat_b is created — creating a second unpersisted
    # chat before the first ever gets a message would overwrite
    # SessionService's single in-memory "active chat" slot and silently
    # lose chat_a's (never-yet-saved) existence entirely. This is the
    # documented active-session limitation (see chats.py's module
    # docstring), not something this test is trying to exercise.
    chat_a = _create_chat(client)
    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "send_message", "chat_id": chat_a, "content": "Remember ALPHA=1"})
        _drain_until_completed(ws)

    chat_b = _create_chat(client)
    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
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


def test_unknown_message_type_produces_validation_error_event(client):
    chat_id = _create_chat(client)
    with client.websocket_connect("/api/v1/ws/chat", headers=HEADERS) as ws:
        ws.send_json({"type": "not_a_real_type", "chat_id": chat_id, "content": "hi"})
        event = ws.receive_json()
        assert event["type"] == "error"
        assert event["code"] == "VALIDATION_ERROR"
