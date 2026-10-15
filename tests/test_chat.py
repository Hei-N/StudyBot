from typing import Iterator, Sequence

import pytest

from studybot.core.chat import ChatService
from studybot.core.exceptions import ModelError
from studybot.core.messages import Message, Role
from studybot.core.reasoning_mode import DEFAULT_REASONING_MODE, ReasoningMode
from studybot.models.base import ModelCapabilities, ModelResponse, ProviderStatus
from studybot.models.mock import MockModel


class FailingModel:
    """A model provider stub that always raises, for testing error propagation."""

    name = "failing"

    def generate(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> ModelResponse:
        raise ModelError("backend unavailable")


class RecordingModel:
    """Records the exact message sequence (and reasoning mode) it was
    called with, for asserting ordering/context without depending on a
    real backend."""

    name = "recording"

    def __init__(self, reply: str = "ok", chunks: list[str] | None = None) -> None:
        self.reply = reply
        self.chunks = chunks if chunks is not None else [reply]
        self.received_calls: list[list[Message]] = []
        self.received_reasoning_modes: list[ReasoningMode] = []

    def generate(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> ModelResponse:
        self.received_calls.append(list(messages))
        self.received_reasoning_modes.append(reasoning_mode)
        return ModelResponse(content=self.reply, model_name=self.name)

    def stream(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> Iterator[str]:
        self.received_calls.append(list(messages))
        self.received_reasoning_modes.append(reasoning_mode)
        yield from self.chunks

    def get_status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_name=self.name,
            server_reachable=True,
            model_name=self.name,
            model_available=True,
        )


class StreamingFailureModel:
    """Yields some content, then fails partway through streaming."""

    name = "streaming-failure"

    def generate(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> ModelResponse:
        raise ModelError("should not be called in these tests")

    def stream(
        self, messages: Sequence[Message], *, reasoning_mode: ReasoningMode = DEFAULT_REASONING_MODE
    ) -> Iterator[str]:
        yield "partial "
        yield "output"
        raise ModelError("stream broke")

    def get_status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_name=self.name,
            server_reachable=True,
            model_name=self.name,
            model_available=True,
        )


def test_send_appends_user_and_assistant_messages_in_order():
    chat = ChatService(model=MockModel())

    chat.send("hello")

    roles = [m.role for m in chat.history]
    assert roles == [Role.USER, Role.ASSISTANT]


def test_send_returns_assistant_reply():
    chat = ChatService(model=MockModel())

    reply = chat.send("hello")

    assert reply.role is Role.ASSISTANT
    assert reply.content == "[Mock] You said: hello"


def test_multiple_turns_preserve_order():
    chat = ChatService(model=MockModel())

    chat.send("first")
    chat.send("second")

    contents = [m.content for m in chat.history]
    assert contents == [
        "first",
        "[Mock] You said: first",
        "second",
        "[Mock] You said: second",
    ]


def test_system_prompt_is_seeded_and_kept_first():
    chat = ChatService(model=MockModel(), system_prompt="You are a bot.")

    chat.send("hi")

    assert chat.history[0].role is Role.SYSTEM
    assert chat.history[0].content == "You are a bot."


def test_constructor_preloads_history_after_system_prompt():
    prior = [Message.user("earlier question"), Message.assistant("earlier answer")]

    chat = ChatService(model=MockModel(), system_prompt="You are a bot.", history=prior)

    assert [m.role for m in chat.history] == [Role.SYSTEM, Role.USER, Role.ASSISTANT]
    assert [m.content for m in chat.history] == ["You are a bot.", "earlier question", "earlier answer"]


def test_constructor_preloaded_history_is_sent_on_next_send():
    prior = [Message.user("earlier question"), Message.assistant("earlier answer")]
    model = RecordingModel(reply="ack")
    chat = ChatService(model=model, system_prompt="sys", history=prior)

    chat.send("new question")

    sent = model.received_calls[0]
    assert [m.content for m in sent] == ["sys", "earlier question", "earlier answer", "new question"]


def test_clear_empties_history():
    chat = ChatService(model=MockModel())
    chat.send("hello")

    chat.clear()

    assert chat.history == ()


def test_history_is_read_only_view():
    chat = ChatService(model=MockModel())
    chat.send("hello")

    history = chat.history

    assert isinstance(history, tuple)


def test_model_error_propagates_from_send():
    chat = ChatService(model=FailingModel())

    with pytest.raises(ModelError):
        chat.send("hello")


def test_failed_send_does_not_record_assistant_message():
    chat = ChatService(model=FailingModel())

    with pytest.raises(ModelError):
        chat.send("hello")

    roles = [m.role for m in chat.history]
    assert roles == [Role.USER]


def test_multi_turn_context_is_passed_to_model_in_order():
    model = RecordingModel(reply="ack")
    chat = ChatService(model=model, system_prompt="sys")

    chat.send("first")
    chat.send("second")

    second_call_messages = model.received_calls[1]
    assert [m.role for m in second_call_messages] == [
        Role.SYSTEM,
        Role.USER,
        Role.ASSISTANT,
        Role.USER,
    ]
    assert [m.content for m in second_call_messages] == ["sys", "first", "ack", "second"]


def test_system_prompt_is_first_message_sent_to_model():
    model = RecordingModel(reply="ack")
    chat = ChatService(model=model, system_prompt="You are a helpful local study assistant.")

    chat.send("hi")

    first_call_messages = model.received_calls[0]
    assert first_call_messages[0].role is Role.SYSTEM
    assert first_call_messages[0].content == "You are a helpful local study assistant."
    assert first_call_messages[1].role is Role.USER


def test_get_status_delegates_to_model():
    chat = ChatService(model=RecordingModel())

    status = chat.get_status()

    assert status.provider_name == "recording"
    assert status.server_reachable is True


# --- streaming ---------------------------------------------------------------


def test_send_streaming_yields_each_chunk():
    model = RecordingModel(chunks=["Hello", " ", "world"])
    chat = ChatService(model=model)

    chunks = list(chat.send_streaming("hi"))

    assert chunks == ["Hello", " ", "world"]


def test_send_streaming_records_one_complete_assistant_message():
    model = RecordingModel(chunks=["Hello", " ", "world"])
    chat = ChatService(model=model)

    list(chat.send_streaming("hi"))

    roles = [m.role for m in chat.history]
    assert roles == [Role.USER, Role.ASSISTANT]
    assert chat.history[-1].content == "Hello world"


def test_no_assistant_message_recorded_until_stream_completes():
    model = RecordingModel(chunks=["a", "b", "c"])
    chat = ChatService(model=model)

    generator = chat.send_streaming("hi")
    next(generator)  # only the first chunk has been produced so far

    assert [m.role for m in chat.history] == [Role.USER]

    for _ in generator:
        pass  # drain the rest

    assert [m.role for m in chat.history] == [Role.USER, Role.ASSISTANT]
    assert chat.history[-1].content == "abc"


def test_abandoning_a_stream_early_does_not_record_assistant_message():
    model = RecordingModel(chunks=["a", "b", "c"])
    chat = ChatService(model=model)

    generator = chat.send_streaming("hi")
    next(generator)
    generator.close()

    assert [m.role for m in chat.history] == [Role.USER]


def test_streaming_failure_propagates_and_does_not_record_assistant_message():
    chat = ChatService(model=StreamingFailureModel())

    received: list[str] = []
    with pytest.raises(ModelError):
        for chunk in chat.send_streaming("hi"):
            received.append(chunk)

    assert received == ["partial ", "output"]
    assert [m.role for m in chat.history] == [Role.USER]


class CapabilitiesModel:
    """Returns a distinctive capabilities object and records how often it
    was asked; to prove `ChatService` is a pure pass-through."""

    name = "capabilities"
    CAPABILITIES = ModelCapabilities(True, False, True, False, 4096)

    def __init__(self) -> None:
        self.calls = 0

    def get_capabilities(self) -> ModelCapabilities:
        self.calls += 1
        return self.CAPABILITIES


def test_get_capabilities_delegates_exactly_to_the_model_provider():
    model = CapabilitiesModel()
    chat = ChatService(model)

    assert chat.get_capabilities() is CapabilitiesModel.CAPABILITIES
    assert model.calls == 1


def test_get_capabilities_does_not_touch_history():
    chat = ChatService(CapabilitiesModel(), system_prompt="sys", history=[Message.user("hi")])
    before = chat.history

    chat.get_capabilities()

    assert chat.history == before


# --- generation budget failures ------------------------------------------------------

from studybot.core.exceptions import GenerationDeadlineExceededError, GenerationTokenLimitExceededError

BUDGET_ERRORS = [GenerationDeadlineExceededError(120.0), GenerationTokenLimitExceededError(2048)]


class BudgetFailingThenOkModel:
    """Streams some text and then fails with a budget error on the first
    call; every later call succeeds."""

    name = "budget-flaky"

    def __init__(self, error):
        self.error = error
        self.calls = 0

    def generate(self, messages, *, reasoning_mode=DEFAULT_REASONING_MODE):
        self.calls += 1
        if self.calls == 1:
            raise self.error
        return ModelResponse(content="recovered", model_name=self.name)

    def stream(self, messages, *, reasoning_mode=DEFAULT_REASONING_MODE):
        self.calls += 1
        if self.calls == 1:
            yield "partial "
            yield "text"
            raise self.error
        yield "recov"
        yield "ered"


@pytest.mark.parametrize("error", BUDGET_ERRORS, ids=lambda e: type(e).__name__)
def test_a_budget_failure_during_streaming_keeps_only_the_user_message(error):
    chat = ChatService(BudgetFailingThenOkModel(error))
    received = []

    with pytest.raises(type(error)):
        for chunk in chat.send_streaming("hello"):
            received.append(chunk)

    assert received == ["partial ", "text"]  # what the model streamed is the caller's to discard
    assert [(m.role, m.content) for m in chat.history] == [(Role.USER, "hello")]


@pytest.mark.parametrize("error", BUDGET_ERRORS, ids=lambda e: type(e).__name__)
def test_a_budget_failure_in_send_keeps_only_the_user_message(error):
    chat = ChatService(BudgetFailingThenOkModel(error))

    with pytest.raises(type(error)):
        chat.send("hello")

    assert [(m.role, m.content) for m in chat.history] == [(Role.USER, "hello")]


@pytest.mark.parametrize("error", BUDGET_ERRORS, ids=lambda e: type(e).__name__)
def test_the_chat_stays_usable_after_a_budget_failure(error):
    chat = ChatService(BudgetFailingThenOkModel(error))
    with pytest.raises(type(error)):
        list(chat.send_streaming("first"))

    reply = "".join(chat.send_streaming("second"))

    assert reply == "recovered"
    assert [m.role for m in chat.history] == [Role.USER, Role.USER, Role.ASSISTANT]
    assert chat.history[-1].content == "recovered"


@pytest.mark.parametrize("error", BUDGET_ERRORS, ids=lambda e: type(e).__name__)
def test_budget_errors_are_ordinary_model_errors_for_every_existing_handler(error):
    assert isinstance(error, ModelError)
    with pytest.raises(ModelError):
        ChatService(BudgetFailingThenOkModel(error)).send("hello")


def test_empty_progress_chunks_never_enter_chat_history():
    class ProgressModel:
        name = "progress"

        def generate(self, messages, *, reasoning_mode=DEFAULT_REASONING_MODE):
            raise NotImplementedError

        def stream(self, messages, *, reasoning_mode=DEFAULT_REASONING_MODE):
            yield ""
            yield "Hel"
            yield ""
            yield "lo"
            yield ""

    chat = ChatService(ProgressModel())
    assert "".join(chat.send_streaming("hi")) == "Hello"
    assert chat.history[-1].content == "Hello"
