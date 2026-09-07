import httpx
import ollama
import pytest

from studybot.core.exceptions import ModelError
from studybot.core.messages import Message
from studybot.models.ollama import OllamaModel
from tests.fake_ollama import FakeChatResponse, FakeListResponse, FakeOllamaClient


def make_model(client: FakeOllamaClient, model: str = "qwen3:4b") -> OllamaModel:
    return OllamaModel(model=model, host="http://localhost:11434", client=client)


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


# --- streaming ---------------------------------------------------------------


def test_stream_yields_each_chunk_of_content():
    def stream_factory():
        yield FakeChatResponse("Hello")
        yield FakeChatResponse(" world")

    fake = FakeOllamaClient(stream_factory=stream_factory)
    model = make_model(fake)

    chunks = list(model.stream([Message.user("hi")]))

    assert chunks == ["Hello", " world"]


def test_stream_skips_empty_or_none_content_chunks():
    def stream_factory():
        yield FakeChatResponse("Hello")
        yield FakeChatResponse(None)
        yield FakeChatResponse("")
        yield FakeChatResponse(" world")

    fake = FakeOllamaClient(stream_factory=stream_factory)
    model = make_model(fake)

    chunks = list(model.stream([Message.user("hi")]))

    assert chunks == ["Hello", " world"]


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
