import pytest

from studybot.core.exceptions import ModelError, SessionError
from studybot.core.messages import Role
from studybot.core.session_service import SessionService
from studybot.models.base import ModelResponse, ProviderStatus
from studybot.models.mock import MockModel
from studybot.storage.sqlite_repository import SQLiteChatRepository


class RecordingModel:
    """Records the exact message sequence it was called with."""

    name = "recording"

    def __init__(self, reply: str = "ok", chunks: list[str] | None = None) -> None:
        self.reply = reply
        self.chunks = chunks if chunks is not None else [reply]
        self.received_calls: list[list] = []

    def generate(self, messages):
        self.received_calls.append(list(messages))
        return ModelResponse(content=self.reply, model_name=self.name)

    def stream(self, messages):
        self.received_calls.append(list(messages))
        yield from self.chunks

    def get_status(self):
        return ProviderStatus(
            provider_name=self.name, server_reachable=True, model_name=self.name, model_available=True
        )


class FailingModel:
    """Fails on both generate and stream, for error-propagation tests."""

    name = "failing"

    def generate(self, messages):
        raise ModelError("model is down")

    def stream(self, messages):
        raise ModelError("model is down")
        yield  # pragma: no cover - never reached; keeps this a generator function

    def get_status(self):
        return ProviderStatus(
            provider_name=self.name, server_reachable=False, model_name=self.name, model_available=None
        )


class FailingStreamModel:
    """Yields some content, then fails partway through streaming."""

    name = "failing-stream"

    def generate(self, messages):
        raise AssertionError("not used in these tests")

    def stream(self, messages):
        yield "partial "
        raise ModelError("stream broke")

    def get_status(self):
        return ProviderStatus(
            provider_name=self.name, server_reachable=True, model_name=self.name, model_available=True
        )


@pytest.fixture
def repository(tmp_path):
    repo = SQLiteChatRepository(tmp_path / "studybot-test.db")
    yield repo
    repo.close()


def make_service(repository, model=None, system_prompt="sys prompt"):
    return SessionService(model=model or MockModel(), repository=repository, system_prompt=system_prompt)


def content_only(history):
    return [m.content for m in history if m.role is not Role.SYSTEM]


# --- startup / lazy persistence -----------------------------------------------


def test_starts_with_untitled_in_memory_chat_when_no_chats_exist(repository):
    service = make_service(repository)

    assert service.active_session.title is None
    assert repository.list_chats() == []  # launching alone writes nothing


def test_sending_first_message_creates_persisted_chat_with_generated_title(repository):
    service = make_service(repository)

    service.send("Explain vectors please")

    chats = repository.list_chats()
    assert len(chats) == 1
    assert chats[0].id == service.active_session.id
    assert chats[0].title == "Explain vectors please"


# --- multiple chats / isolation ------------------------------------------------


def test_new_chat_starts_separate_empty_history(repository):
    service = make_service(repository)
    service.send("first chat message")

    service.new_chat()

    assert content_only(service.history) == []


def test_switching_chats_does_not_mix_histories(repository):
    service = make_service(repository)
    service.send("Remember Alpha = 17")
    chat1_id = service.active_session.id

    service.new_chat()
    service.send("Remember Beta = 84")
    chat2_id = service.active_session.id

    service.open_chat(chat1_id)
    assert content_only(service.history) == [
        "Remember Alpha = 17",
        "[Mock] You said: Remember Alpha = 17",
    ]

    service.open_chat(chat2_id)
    assert content_only(service.history) == [
        "Remember Beta = 84",
        "[Mock] You said: Remember Beta = 84",
    ]


def test_open_chat_by_unique_id_prefix(repository):
    service = make_service(repository)
    service.send("chat one")
    chat_id = service.active_session.id
    service.new_chat()
    service.send("chat two")

    opened = service.open_chat(chat_id[:8])

    assert opened.id == chat_id


def test_open_chat_raises_for_unknown_id(repository):
    service = make_service(repository)

    with pytest.raises(SessionError):
        service.open_chat("does-not-exist")


def test_open_chat_raises_for_ambiguous_prefix(repository, monkeypatch):
    ids = iter(["abc111-one", "abc222-two"])
    monkeypatch.setattr("uuid.uuid4", lambda: next(ids))
    service = make_service(repository)
    service.send("first")
    service.new_chat()
    service.send("second")

    with pytest.raises(SessionError):
        service.open_chat("abc")


# --- restart / recreation -------------------------------------------------------


def test_reopening_chat_restores_history_after_recreating_service(repository):
    service1 = make_service(repository)
    service1.send("hello persisted")
    chat_id = service1.active_session.id

    # A brand-new SessionService simulates the app restarting.
    service2 = make_service(repository)

    assert service2.active_session.id == chat_id  # most recently updated, auto-resumed
    assert content_only(service2.history) == ["hello persisted", "[Mock] You said: hello persisted"]


def test_most_recently_updated_chat_is_auto_resumed(repository):
    service = make_service(repository)
    service.send("first chat")
    service.new_chat()
    service.send("second chat")
    second_id = service.active_session.id

    resumed = make_service(repository)

    assert resumed.active_session.id == second_id


def test_restored_conversation_produces_correct_model_input_order(repository):
    model = RecordingModel(reply="ack")
    service = SessionService(model=model, repository=repository, system_prompt="You are helpful.")
    service.send("first turn")
    chat_id = service.active_session.id

    service2 = SessionService(model=model, repository=repository, system_prompt="You are helpful.")
    assert service2.active_session.id == chat_id
    service2.send("second turn")

    last_call = model.received_calls[-1]
    assert [m.role for m in last_call] == [Role.SYSTEM, Role.USER, Role.ASSISTANT, Role.USER]
    assert [m.content for m in last_call] == ["You are helpful.", "first turn", "ack", "second turn"]
    assert sum(1 for m in last_call if m.role is Role.SYSTEM) == 1


# --- titles ----------------------------------------------------------------------


def test_explicit_rename_overrides_generated_title(repository):
    service = make_service(repository)
    service.send("Explain vectors")

    service.rename_active_chat("My Custom Title")
    service.send("more content")

    assert repository.get_chat(service.active_session.id).title == "My Custom Title"


def test_renaming_before_first_message_is_honored_once_persisted(repository):
    service = make_service(repository)

    service.rename_active_chat("Pre-named")
    assert repository.list_chats() == []  # still not persisted

    service.send("hello")

    chats = repository.list_chats()
    assert len(chats) == 1
    assert chats[0].title == "Pre-named"


def test_rename_with_empty_title_raises(repository):
    service = make_service(repository)

    with pytest.raises(SessionError):
        service.rename_active_chat("   ")


# --- streaming persistence --------------------------------------------------------


def test_successful_stream_persists_one_complete_assistant_message(repository):
    model = RecordingModel(chunks=["Hello", " ", "world"])
    service = make_service(repository, model=model)

    list(service.send_streaming("hi"))

    messages = repository.load_messages(service.active_session.id)
    assert [(m.role, m.content) for m in messages] == [
        (Role.USER, "hi"),
        (Role.ASSISTANT, "Hello world"),
    ]


def test_failed_stream_persists_only_the_user_message(repository):
    service = make_service(repository, model=FailingStreamModel())

    with pytest.raises(ModelError):
        list(service.send_streaming("hi"))

    messages = repository.load_messages(service.active_session.id)
    assert [(m.role, m.content) for m in messages] == [(Role.USER, "hi")]


def test_abandoned_stream_persists_only_the_user_message(repository):
    model = RecordingModel(chunks=["a", "b", "c"])
    service = make_service(repository, model=model)

    generator = service.send_streaming("hi")
    next(generator)
    generator.close()

    messages = repository.load_messages(service.active_session.id)
    assert [(m.role, m.content) for m in messages] == [(Role.USER, "hi")]


def test_model_failure_on_non_streaming_send_leaves_only_user_message(repository):
    service = make_service(repository, model=FailingModel())

    with pytest.raises(ModelError):
        service.send("Explain vectors")

    messages = repository.load_messages(service.active_session.id)
    assert [(m.role, m.content) for m in messages] == [(Role.USER, "Explain vectors")]


# --- clear vs delete --------------------------------------------------------------


def test_clear_active_chat_removes_messages_but_keeps_the_chat(repository):
    service = make_service(repository)
    service.send("hello")
    chat_id = service.active_session.id

    service.clear_active_chat()

    assert repository.get_chat(chat_id) is not None
    assert repository.load_messages(chat_id) == []
    assert content_only(service.history) == []


def test_clear_still_injects_system_prompt_on_next_send(repository):
    model = RecordingModel(reply="ack")
    service = SessionService(model=model, repository=repository, system_prompt="sys prompt")
    service.send("hello")

    service.clear_active_chat()
    service.send("hello again")

    last_call = model.received_calls[-1]
    assert [m.content for m in last_call] == ["sys prompt", "hello again"]


def test_delete_active_chat_removes_it_and_activates_another(repository):
    service = make_service(repository)
    service.send("first")
    first_id = service.active_session.id
    service.new_chat()
    service.send("second")
    second_id = service.active_session.id

    deleted = service.delete_active_chat()

    assert deleted.id == second_id
    assert repository.get_chat(second_id) is None
    assert service.active_session.id == first_id


def test_deleting_the_only_chat_creates_a_fresh_untitled_chat(repository):
    service = make_service(repository)
    service.send("only chat")
    only_id = service.active_session.id

    service.delete_active_chat()

    assert repository.list_chats() == []
    assert service.active_session.id != only_id
    assert service.active_session.title is None


def test_deleting_an_unpersisted_chat_does_not_error(repository):
    service = make_service(repository)  # brand new, never sent a message

    service.delete_active_chat()

    assert repository.list_chats() == []


# --- misc passthroughs --------------------------------------------------------------


def test_list_chats_reflects_repository_state(repository):
    service = make_service(repository)
    service.send("a")

    assert [c.id for c in service.list_chats()] == [service.active_session.id]


def test_get_status_delegates_to_model(repository):
    service = make_service(repository, model=RecordingModel())

    status = service.get_status()

    assert status.provider_name == "recording"
