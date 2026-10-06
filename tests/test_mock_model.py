import pytest

from studybot.core.exceptions import ModelError
from studybot.core.messages import Message
from studybot.core.reasoning_mode import ReasoningMode
from studybot.models.base import ModelCapabilities
from studybot.models.mock import MockModel


def test_mock_model_echoes_last_user_message():
    model = MockModel()
    response = model.generate([Message.user("hello")])

    assert response.content == "[Mock] You said: hello"
    assert response.model_name == "mock"


def test_mock_model_uses_most_recent_user_message():
    model = MockModel()
    messages = [
        Message.user("first"),
        Message.assistant("[Mock] You said: first"),
        Message.user("second"),
    ]

    response = model.generate(messages)

    assert response.content == "[Mock] You said: second"


def test_mock_model_ignores_system_message_when_responding():
    model = MockModel()
    messages = [Message.system("You are a bot."), Message.user("hi")]

    response = model.generate(messages)

    assert response.content == "[Mock] You said: hi"


def test_mock_model_is_deterministic():
    model = MockModel()
    messages = [Message.user("repeat me")]

    first = model.generate(messages)
    second = model.generate(messages)

    assert first.content == second.content


def test_mock_model_raises_model_error_with_no_user_message():
    model = MockModel()

    with pytest.raises(ModelError):
        model.generate([Message.system("You are a bot.")])


def test_mock_model_raises_model_error_with_empty_messages():
    model = MockModel()

    with pytest.raises(ModelError):
        model.generate([])


def test_mock_model_accepts_and_ignores_reasoning_mode():
    """A capability the mock has no concept of at all — accepted uniformly
    (not rejected) but deliberately produces no behavior difference."""
    model = MockModel()
    messages = [Message.user("hello")]

    fast = model.generate(messages, reasoning_mode=ReasoningMode.FAST)
    deep = model.generate(messages, reasoning_mode=ReasoningMode.DEEP)

    assert fast.content == deep.content


def test_mock_model_stream_accepts_and_ignores_reasoning_mode():
    model = MockModel()
    messages = [Message.user("hello")]

    fast_chunks = list(model.stream(messages, reasoning_mode=ReasoningMode.FAST))
    deep_chunks = list(model.stream(messages, reasoning_mode=ReasoningMode.DEEP))

    assert fast_chunks == deep_chunks


def test_mock_model_capabilities_are_exactly_the_specified_constants():
    assert MockModel().get_capabilities() == ModelCapabilities(
        supports_vision=False,
        supports_tools=False,
        supports_thinking=False,
        reasoning_modes_distinct=False,
        context_window=None,
    )
