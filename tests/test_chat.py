from typing import Sequence

import pytest

from studybot.core.chat import ChatService
from studybot.core.exceptions import ModelError
from studybot.core.messages import Message, Role
from studybot.models.base import ModelResponse
from studybot.models.mock import MockModel


class FailingModel:
    """A model provider stub that always raises, for testing error propagation."""

    name = "failing"

    def generate(self, messages: Sequence[Message]) -> ModelResponse:
        raise ModelError("backend unavailable")


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
