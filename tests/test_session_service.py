import pytest

from studybot.core.exceptions import ModelError, SessionError
from studybot.core.messages import Role
from studybot.core.mode_prompts import get_mode_prompt
from studybot.core.reasoning_mode import ReasoningMode
from studybot.core.session_service import SessionService
from studybot.core.teaching_mode import TeachingMode
from studybot.models.base import ModelResponse, ProviderStatus
from studybot.models.mock import MockModel
from studybot.storage.database import open_database
from studybot.storage.sqlite_course_repository import SQLiteCourseRepository
from studybot.storage.sqlite_repository import SQLiteChatRepository


class RecordingModel:
    """Records the exact message sequence (and reasoning mode) it was
    called with."""

    name = "recording"

    def __init__(self, reply: str = "ok", chunks: list[str] | None = None) -> None:
        self.reply = reply
        self.chunks = chunks if chunks is not None else [reply]
        self.received_calls: list[list] = []
        self.received_reasoning_modes: list[ReasoningMode] = []

    def generate(self, messages, *, reasoning_mode=None):
        self.received_calls.append(list(messages))
        self.received_reasoning_modes.append(reasoning_mode)
        return ModelResponse(content=self.reply, model_name=self.name)

    def stream(self, messages, *, reasoning_mode=None):
        self.received_calls.append(list(messages))
        self.received_reasoning_modes.append(reasoning_mode)
        yield from self.chunks

    def get_status(self):
        return ProviderStatus(
            provider_name=self.name, server_reachable=True, model_name=self.name, model_available=True
        )


class FailingModel:
    """Fails on both generate and stream, for error-propagation tests."""

    name = "failing"

    def generate(self, messages, *, reasoning_mode=None):
        raise ModelError("model is down")

    def stream(self, messages, *, reasoning_mode=None):
        raise ModelError("model is down")
        yield  # pragma: no cover - never reached; keeps this a generator function

    def get_status(self):
        return ProviderStatus(
            provider_name=self.name, server_reachable=False, model_name=self.name, model_available=None
        )


class FailingStreamModel:
    """Yields some content, then fails partway through streaming."""

    name = "failing-stream"

    def generate(self, messages, *, reasoning_mode=None):
        raise AssertionError("not used in these tests")

    def stream(self, messages, *, reasoning_mode=None):
        yield "partial "
        raise ModelError("stream broke")

    def get_status(self):
        return ProviderStatus(
            provider_name=self.name, server_reachable=True, model_name=self.name, model_available=True
        )


@pytest.fixture
def connection(tmp_path):
    conn = open_database(tmp_path / "studybot-test.db")
    yield conn
    conn.close()


@pytest.fixture
def repository(connection):
    return SQLiteChatRepository(connection)


@pytest.fixture
def course_repository(connection):
    return SQLiteCourseRepository(connection)


def make_service(repository, course_repository, model=None, system_prompt="sys prompt"):
    return SessionService(
        model=model or MockModel(),
        repository=repository,
        course_repository=course_repository,
        system_prompt=system_prompt,
    )


def content_only(history):
    return [m.content for m in history if m.role is not Role.SYSTEM]


# --- startup / lazy persistence -----------------------------------------------


def test_starts_with_untitled_in_memory_chat_when_no_chats_exist(repository, course_repository):
    service = make_service(repository, course_repository)

    assert service.active_session.title is None
    assert service.active_session.course_id is None
    assert repository.list_chats() == []  # launching alone writes nothing


def test_sending_first_message_creates_persisted_chat_with_generated_title(repository, course_repository):
    service = make_service(repository, course_repository)

    service.send("Explain vectors please")

    chats = repository.list_chats()
    assert len(chats) == 1
    assert chats[0].id == service.active_session.id
    assert chats[0].title == "Explain vectors please"


# --- multiple chats / isolation ------------------------------------------------


def test_new_chat_starts_separate_empty_history(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("first chat message")

    service.new_chat()

    assert content_only(service.history) == []


def test_switching_chats_does_not_mix_histories(repository, course_repository):
    service = make_service(repository, course_repository)
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


def test_open_chat_by_unique_id_prefix(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("chat one")
    chat_id = service.active_session.id
    service.new_chat()
    service.send("chat two")

    opened = service.open_chat(chat_id[:8])

    assert opened.id == chat_id


def test_open_chat_raises_for_unknown_id(repository, course_repository):
    service = make_service(repository, course_repository)

    with pytest.raises(SessionError):
        service.open_chat("does-not-exist")


def test_open_chat_raises_for_ambiguous_prefix(repository, course_repository, monkeypatch):
    ids = iter(["abc111-one", "abc222-two"])
    monkeypatch.setattr("uuid.uuid4", lambda: next(ids))
    service = make_service(repository, course_repository)
    service.send("first")
    service.new_chat()
    service.send("second")

    with pytest.raises(SessionError):
        service.open_chat("abc")


# --- restart / recreation -------------------------------------------------------


def test_reopening_chat_restores_history_after_recreating_service(repository, course_repository):
    service1 = make_service(repository, course_repository)
    service1.send("hello persisted")
    chat_id = service1.active_session.id

    # A brand-new SessionService simulates the app restarting.
    service2 = make_service(repository, course_repository)

    assert service2.active_session.id == chat_id  # most recently updated, auto-resumed
    assert content_only(service2.history) == ["hello persisted", "[Mock] You said: hello persisted"]


def test_most_recently_updated_chat_is_auto_resumed(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("first chat")
    service.new_chat()
    service.send("second chat")
    second_id = service.active_session.id

    resumed = make_service(repository, course_repository)

    assert resumed.active_session.id == second_id


def test_restored_conversation_produces_correct_model_input_order(repository, course_repository):
    model = RecordingModel(reply="ack")
    service = SessionService(
        model=model, repository=repository, course_repository=course_repository,
        system_prompt="You are helpful.",
    )
    service.send("first turn")
    chat_id = service.active_session.id

    service2 = SessionService(
        model=model, repository=repository, course_repository=course_repository,
        system_prompt="You are helpful.",
    )
    assert service2.active_session.id == chat_id
    service2.send("second turn")

    last_call = model.received_calls[-1]
    expected_system = "You are helpful.\n\n" + get_mode_prompt(TeachingMode.TEACH)
    assert [m.role for m in last_call] == [Role.SYSTEM, Role.USER, Role.ASSISTANT, Role.USER]
    assert [m.content for m in last_call] == [expected_system, "first turn", "ack", "second turn"]
    assert sum(1 for m in last_call if m.role is Role.SYSTEM) == 1


# --- titles ----------------------------------------------------------------------


def test_explicit_rename_overrides_generated_title(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("Explain vectors")

    service.rename_active_chat("My Custom Title")
    service.send("more content")

    assert repository.get_chat(service.active_session.id).title == "My Custom Title"


def test_renaming_before_first_message_is_honored_once_persisted(repository, course_repository):
    service = make_service(repository, course_repository)

    service.rename_active_chat("Pre-named")
    assert repository.list_chats() == []  # still not persisted

    service.send("hello")

    chats = repository.list_chats()
    assert len(chats) == 1
    assert chats[0].title == "Pre-named"


def test_rename_with_empty_title_raises(repository, course_repository):
    service = make_service(repository, course_repository)

    with pytest.raises(SessionError):
        service.rename_active_chat("   ")


# --- streaming persistence --------------------------------------------------------


def test_successful_stream_persists_one_complete_assistant_message(repository, course_repository):
    model = RecordingModel(chunks=["Hello", " ", "world"])
    service = make_service(repository, course_repository, model=model)

    list(service.send_streaming("hi"))

    messages = repository.load_messages(service.active_session.id)
    assert [(m.role, m.content) for m in messages] == [
        (Role.USER, "hi"),
        (Role.ASSISTANT, "Hello world"),
    ]


def test_failed_stream_persists_only_the_user_message(repository, course_repository):
    service = make_service(repository, course_repository, model=FailingStreamModel())

    with pytest.raises(ModelError):
        list(service.send_streaming("hi"))

    messages = repository.load_messages(service.active_session.id)
    assert [(m.role, m.content) for m in messages] == [(Role.USER, "hi")]


def test_abandoned_stream_persists_only_the_user_message(repository, course_repository):
    model = RecordingModel(chunks=["a", "b", "c"])
    service = make_service(repository, course_repository, model=model)

    generator = service.send_streaming("hi")
    next(generator)
    generator.close()

    messages = repository.load_messages(service.active_session.id)
    assert [(m.role, m.content) for m in messages] == [(Role.USER, "hi")]


def test_model_failure_on_non_streaming_send_leaves_only_user_message(repository, course_repository):
    service = make_service(repository, course_repository, model=FailingModel())

    with pytest.raises(ModelError):
        service.send("Explain vectors")

    messages = repository.load_messages(service.active_session.id)
    assert [(m.role, m.content) for m in messages] == [(Role.USER, "Explain vectors")]


# --- clear vs delete --------------------------------------------------------------


def test_clear_active_chat_removes_messages_but_keeps_the_chat(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")
    chat_id = service.active_session.id

    service.clear_active_chat()

    assert repository.get_chat(chat_id) is not None
    assert repository.load_messages(chat_id) == []
    assert content_only(service.history) == []


def test_clear_still_injects_system_prompt_on_next_send(repository, course_repository):
    model = RecordingModel(reply="ack")
    service = SessionService(
        model=model, repository=repository, course_repository=course_repository,
        system_prompt="sys prompt",
    )
    service.send("hello")

    service.clear_active_chat()
    service.send("hello again")

    last_call = model.received_calls[-1]
    expected_system = "sys prompt\n\n" + get_mode_prompt(TeachingMode.TEACH)
    assert [m.content for m in last_call] == [expected_system, "hello again"]


def test_delete_active_chat_removes_it_and_activates_another(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("first")
    first_id = service.active_session.id
    service.new_chat()
    service.send("second")
    second_id = service.active_session.id

    deleted = service.delete_active_chat()

    assert deleted.id == second_id
    assert repository.get_chat(second_id) is None
    assert service.active_session.id == first_id


def test_deleting_the_only_chat_creates_a_fresh_untitled_chat(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("only chat")
    only_id = service.active_session.id

    service.delete_active_chat()

    assert repository.list_chats() == []
    assert service.active_session.id != only_id
    assert service.active_session.title is None


def test_deleting_an_unpersisted_chat_does_not_error(repository, course_repository):
    service = make_service(repository, course_repository)  # brand new, never sent a message

    service.delete_active_chat()

    assert repository.list_chats() == []


# --- misc passthroughs --------------------------------------------------------------


def test_list_chats_reflects_repository_state(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("a")

    assert [c.id for c in service.list_chats()] == [service.active_session.id]


def test_get_status_delegates_to_model(repository, course_repository):
    service = make_service(repository, course_repository, model=RecordingModel())

    status = service.get_status()

    assert status.provider_name == "recording"


# --- course context: new chats, isolation, system prompt ----------------------------


def test_new_chat_inherits_active_course_by_default(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.open_course_context(course.id)

    service.new_chat()

    assert service.active_session.course_id == course.id


def test_new_chat_can_target_a_different_course_explicitly(repository, course_repository):
    physics = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)

    service.new_chat(course_id=physics.id)

    assert service.active_session.course_id == physics.id


def test_open_course_context_resumes_most_recent_chat_in_that_course(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.new_chat(course_id=course.id)
    service.send("physics chat one")
    chat_id = service.active_session.id

    service.new_chat(course_id=None)  # switch away to General
    service.send("unrelated general chat")

    service.open_course_context(course.id)

    assert service.active_session.id == chat_id


def test_open_course_context_with_no_chats_starts_empty_chat_scoped_to_course(
    repository, course_repository
):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)

    session = service.open_course_context(course.id)

    assert session.course_id == course.id
    assert session.title is None
    assert repository.list_chats() == []  # nothing persisted just from opening


def test_leaving_course_via_none_context_goes_to_general(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.open_course_context(course.id)

    session = service.open_course_context(None)

    assert session.course_id is None


def test_three_way_chat_isolation_across_two_courses_and_general(repository, course_repository):
    """Physics/Chat A, Physics/Chat B, and Calculus/Chat C must never see
    each other's history, even though two of them share a course."""
    physics = course_repository.create_course("physics", "Physics", None, None, None)
    calculus = course_repository.create_course("calc", "Calculus", None, None, None)
    service = make_service(repository, course_repository)

    service.new_chat(course_id=physics.id)
    service.send("Remember PHYSICS_A = 1")
    chat_a = service.active_session.id

    service.new_chat(course_id=physics.id)
    service.send("Remember PHYSICS_B = 2")
    chat_b = service.active_session.id

    service.new_chat(course_id=calculus.id)
    service.send("Remember CALC_C = 3")
    chat_c = service.active_session.id

    service.open_chat(chat_a)
    assert content_only(service.history) == ["Remember PHYSICS_A = 1", "[Mock] You said: Remember PHYSICS_A = 1"]

    service.open_chat(chat_b)
    assert content_only(service.history) == ["Remember PHYSICS_B = 2", "[Mock] You said: Remember PHYSICS_B = 2"]

    service.open_chat(chat_c)
    assert content_only(service.history) == ["Remember CALC_C = 3", "[Mock] You said: Remember CALC_C = 3"]


def test_course_context_appears_in_model_input(repository, course_repository):
    course_repository.create_course("c1", "University Physics I", "PHY 215", "Fall 2026", None)
    model = RecordingModel(reply="ack")
    service = SessionService(
        model=model, repository=repository, course_repository=course_repository,
        system_prompt="Baseline.",
    )
    service.new_chat(course_id="c1")

    service.send("hello")

    system_message = model.received_calls[-1][0]
    assert system_message.role is Role.SYSTEM
    assert "University Physics I" in system_message.content
    assert "PHY 215" in system_message.content
    assert "Baseline." in system_message.content


def test_general_chat_has_no_course_context_in_model_input(repository, course_repository):
    model = RecordingModel(reply="ack")
    service = SessionService(
        model=model, repository=repository, course_repository=course_repository,
        system_prompt="Baseline.",
    )

    service.send("hello")

    system_message = model.received_calls[-1][0]
    assert system_message.content.startswith("Baseline.")
    assert "Current course:" not in system_message.content


def test_restart_reconstructs_active_course_from_resumed_chat(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", "PHY 100", None, None)
    model = RecordingModel(reply="ack")
    service1 = SessionService(
        model=model, repository=repository, course_repository=course_repository,
        system_prompt="Baseline.",
    )
    service1.new_chat(course_id=course.id)
    service1.send("hello")

    service2 = SessionService(
        model=model, repository=repository, course_repository=course_repository,
        system_prompt="Baseline.",
    )
    assert service2.active_session.course_id == course.id

    service2.send("again")
    system_message = model.received_calls[-1][0]
    assert "Physics" in system_message.content
    assert "PHY 100" in system_message.content


# --- move / unassign chat -----------------------------------------------------------


def test_move_active_chat_to_course_by_id(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.send("hello")

    session = service.move_active_chat_to_course(course.id)

    assert session.course_id == course.id
    assert repository.get_chat(session.id).course_id == course.id


def test_move_active_chat_to_course_by_prefix(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.send("hello")

    session = service.move_active_chat_to_course(course.id[:1])

    assert session.course_id == course.id


def test_move_active_chat_preserves_messages_and_id(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.send("hello")
    chat_id = service.active_session.id

    service.move_active_chat_to_course(course.id)

    assert service.active_session.id == chat_id
    assert [m.content for m in repository.load_messages(chat_id)] == ["hello", "[Mock] You said: hello"]


def test_move_active_chat_to_none_unassigns(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.new_chat(course_id=course.id)
    service.send("hello")

    session = service.move_active_chat_to_course(None)

    assert session.course_id is None


def test_move_unpersisted_chat_to_course(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)  # unpersisted

    service.move_active_chat_to_course(course.id)
    service.send("hello")  # first persist

    assert repository.get_chat(service.active_session.id).course_id == course.id


def test_move_active_chat_raises_for_unknown_course(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")

    with pytest.raises(SessionError):
        service.move_active_chat_to_course("does-not-exist")


def test_moving_chat_updates_effective_system_prompt(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    model = RecordingModel(reply="ack")
    service = SessionService(
        model=model, repository=repository, course_repository=course_repository,
        system_prompt="Baseline.",
    )
    service.send("hello")

    service.move_active_chat_to_course(course.id)
    service.send("again")

    system_message = model.received_calls[-1][0]
    assert "Physics" in system_message.content


# --- delete chat/course interplay ----------------------------------------------------


def test_deleting_active_chat_prefers_another_chat_in_the_same_course(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.new_chat(course_id=course.id)
    service.send("first")
    first_id = service.active_session.id
    service.new_chat(course_id=course.id)
    service.send("second")
    second_id = service.active_session.id

    service.delete_active_chat()

    assert service.active_session.id == first_id
    assert service.active_session.course_id == course.id


def test_deleting_last_chat_in_course_starts_new_chat_still_scoped_to_course(
    repository, course_repository
):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.new_chat(course_id=course.id)
    service.send("only chat in course")

    service.delete_active_chat()

    assert service.active_session.course_id == course.id
    assert service.active_session.title is None


def test_deleting_course_preserves_its_chats_and_messages(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.new_chat(course_id=course.id)
    service.send("hello")
    chat_id = service.active_session.id

    course_repository.delete_course(course.id)

    chat = repository.get_chat(chat_id)
    assert chat is not None
    assert chat.course_id is None  # unassigned, not deleted
    assert [m.content for m in repository.load_messages(chat_id)] == ["hello", "[Mock] You said: hello"]


def test_sync_active_chat_course_refreshes_without_switching_chats(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    model = RecordingModel(reply="ack")
    service = SessionService(
        model=model, repository=repository, course_repository=course_repository,
        system_prompt="Baseline.",
    )
    service.new_chat(course_id=course.id)
    service.send("hello")
    chat_id = service.active_session.id

    course_repository.delete_course(course.id)
    service.sync_active_chat_course()

    assert service.active_session.id == chat_id  # did not switch chats
    assert service.active_session.course_id is None
    service.send("again")
    system_message = model.received_calls[-1][0]
    assert system_message.content.startswith("Baseline.")
    assert "Current course:" not in system_message.content  # course context dropped


# --- listing chats by course ---------------------------------------------------------


def test_list_chats_in_course_filters_correctly(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.new_chat(course_id=course.id)
    service.send("in course")
    service.new_chat(course_id=None)
    service.send("general")

    in_course = service.list_chats_in_course(course.id)
    general = service.list_chats_in_course(None)

    assert [c.title for c in in_course] == ["in course"]
    assert [c.title for c in general] == ["general"]


# --- teaching mode ---------------------------------------------------------------------


def test_new_chat_defaults_to_teach_mode(repository, course_repository):
    service = make_service(repository, course_repository)

    assert service.get_teaching_mode() is TeachingMode.TEACH
    assert service.active_session.teaching_mode is TeachingMode.TEACH


def test_new_chat_does_not_inherit_previous_chats_mode(repository, course_repository):
    service = make_service(repository, course_repository)
    service.set_teaching_mode(TeachingMode.EXAM)
    service.send("hello")

    service.new_chat()

    assert service.get_teaching_mode() is TeachingMode.TEACH


def test_set_teaching_mode_updates_active_session(repository, course_repository):
    service = make_service(repository, course_repository)

    session = service.set_teaching_mode(TeachingMode.HOMEWORK)

    assert session.teaching_mode is TeachingMode.HOMEWORK
    assert service.get_teaching_mode() is TeachingMode.HOMEWORK


def test_set_teaching_mode_persists_immediately(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")  # persist the chat first

    service.set_teaching_mode(TeachingMode.QUICK)

    assert repository.get_chat(service.active_session.id).teaching_mode is TeachingMode.QUICK


def test_set_teaching_mode_on_unpersisted_chat_is_honored_once_persisted(repository, course_repository):
    service = make_service(repository, course_repository)

    service.set_teaching_mode(TeachingMode.PRACTICE)
    assert repository.list_chats() == []  # still not persisted

    service.send("hello")

    assert repository.get_chat(service.active_session.id).teaching_mode is TeachingMode.PRACTICE


def test_set_teaching_mode_does_not_clear_messages(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")

    service.set_teaching_mode(TeachingMode.EXAM)

    assert content_only(service.history) == ["hello", "[Mock] You said: hello"]


def test_set_teaching_mode_does_not_add_a_history_message(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")
    before = list(service.history)

    service.set_teaching_mode(TeachingMode.EXAM)

    after = [m for m in service.history if m.role is not Role.SYSTEM]
    assert [m.content for m in after] == [m.content for m in before if m.role is not Role.SYSTEM]


def test_set_teaching_mode_does_not_create_a_new_chat(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")
    chat_id = service.active_session.id

    service.set_teaching_mode(TeachingMode.EXAM)

    assert service.active_session.id == chat_id
    assert len(repository.list_chats()) == 1


def test_set_teaching_mode_does_not_alter_course(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.new_chat(course_id=course.id)
    service.send("hello")

    service.set_teaching_mode(TeachingMode.EXAM)

    assert service.active_session.course_id == course.id


def test_set_teaching_mode_does_not_alter_title(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")
    service.rename_active_chat("My Title")

    service.set_teaching_mode(TeachingMode.EXAM)

    assert service.active_session.title == "My Title"


def test_mode_applies_to_next_inference(repository, course_repository):
    model = RecordingModel(reply="ack")
    service = SessionService(
        model=model, repository=repository, course_repository=course_repository,
        system_prompt="Baseline.",
    )
    service.send("hello")

    service.set_teaching_mode(TeachingMode.EXAM)
    service.send("next message")

    system_message = model.received_calls[-1][0]
    assert "Teaching mode: Exam" in system_message.content


def test_rename_does_not_reset_teaching_mode(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")
    service.set_teaching_mode(TeachingMode.EXAM)

    service.rename_active_chat("New Title")

    assert service.active_session.teaching_mode is TeachingMode.EXAM
    assert repository.get_chat(service.active_session.id).teaching_mode is TeachingMode.EXAM


def test_clear_does_not_reset_teaching_mode(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")
    service.set_teaching_mode(TeachingMode.EXAM)

    service.clear_active_chat()

    assert service.active_session.teaching_mode is TeachingMode.EXAM


def test_moving_chat_between_courses_does_not_change_mode(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.send("hello")
    service.set_teaching_mode(TeachingMode.EXAM)

    service.move_active_chat_to_course(course.id)

    assert service.active_session.teaching_mode is TeachingMode.EXAM


def test_deleting_course_does_not_change_chat_mode(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.new_chat(course_id=course.id)
    service.send("hello")
    service.set_teaching_mode(TeachingMode.EXAM)

    course_repository.delete_course(course.id)
    service.sync_active_chat_course()

    assert service.active_session.teaching_mode is TeachingMode.EXAM


def test_mode_persists_across_restart(repository, course_repository):
    service1 = make_service(repository, course_repository)
    service1.send("hello")
    service1.set_teaching_mode(TeachingMode.EXAM)

    service2 = make_service(repository, course_repository)

    assert service2.get_teaching_mode() is TeachingMode.EXAM


def test_different_chats_preserve_different_modes(repository, course_repository):
    """Physics/Chat A -> Homework, Chat B -> Quick, Chat C -> Exam: changing
    one must never change the others, and reopening each restores its own."""
    service = make_service(repository, course_repository)

    service.send("chat a")
    service.set_teaching_mode(TeachingMode.HOMEWORK)
    chat_a = service.active_session.id

    service.new_chat()
    service.send("chat b")
    service.set_teaching_mode(TeachingMode.QUICK)
    chat_b = service.active_session.id

    service.new_chat()
    service.send("chat c")
    service.set_teaching_mode(TeachingMode.EXAM)
    chat_c = service.active_session.id

    service.open_chat(chat_a)
    assert service.get_teaching_mode() is TeachingMode.HOMEWORK
    service.open_chat(chat_b)
    assert service.get_teaching_mode() is TeachingMode.QUICK
    service.open_chat(chat_c)
    assert service.get_teaching_mode() is TeachingMode.EXAM

    # Changing chat A's mode does not affect B or C.
    service.open_chat(chat_a)
    service.set_teaching_mode(TeachingMode.PRACTICE)
    service.open_chat(chat_b)
    assert service.get_teaching_mode() is TeachingMode.QUICK
    service.open_chat(chat_c)
    assert service.get_teaching_mode() is TeachingMode.EXAM


def test_different_chats_preserve_different_modes_across_restart(repository, course_repository):
    service1 = make_service(repository, course_repository)
    service1.send("chat a")
    service1.set_teaching_mode(TeachingMode.HOMEWORK)
    chat_a = service1.active_session.id

    service1.new_chat()
    service1.send("chat b")
    service1.set_teaching_mode(TeachingMode.QUICK)
    chat_b = service1.active_session.id

    service2 = make_service(repository, course_repository)
    assert service2.open_chat(chat_a).teaching_mode is TeachingMode.HOMEWORK
    assert service2.open_chat(chat_b).teaching_mode is TeachingMode.QUICK


# --- reasoning mode ----------------------------------------------------------------


def test_new_chat_defaults_to_fast_reasoning_mode(repository, course_repository):
    service = make_service(repository, course_repository)

    assert service.get_reasoning_mode() is ReasoningMode.FAST
    assert service.active_session.reasoning_mode is ReasoningMode.FAST


def test_new_chat_does_not_inherit_previous_chats_reasoning_mode(repository, course_repository):
    service = make_service(repository, course_repository)
    service.set_reasoning_mode(ReasoningMode.DEEP)
    service.send("hello")

    service.new_chat()

    assert service.get_reasoning_mode() is ReasoningMode.FAST


def test_set_reasoning_mode_updates_active_session(repository, course_repository):
    service = make_service(repository, course_repository)

    session = service.set_reasoning_mode(ReasoningMode.DEEP)

    assert session.reasoning_mode is ReasoningMode.DEEP
    assert service.get_reasoning_mode() is ReasoningMode.DEEP


def test_set_reasoning_mode_persists_immediately(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")  # persist the chat first

    service.set_reasoning_mode(ReasoningMode.DEEP)

    assert repository.get_chat(service.active_session.id).reasoning_mode is ReasoningMode.DEEP


def test_set_reasoning_mode_on_unpersisted_chat_is_honored_once_persisted(repository, course_repository):
    service = make_service(repository, course_repository)

    service.set_reasoning_mode(ReasoningMode.DEEP)
    assert repository.list_chats() == []  # still not persisted

    service.send("hello")

    assert repository.get_chat(service.active_session.id).reasoning_mode is ReasoningMode.DEEP


def test_set_reasoning_mode_does_not_clear_messages(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")

    service.set_reasoning_mode(ReasoningMode.DEEP)

    assert content_only(service.history) == ["hello", "[Mock] You said: hello"]


def test_set_reasoning_mode_does_not_add_a_history_message(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")
    before = list(service.history)

    service.set_reasoning_mode(ReasoningMode.DEEP)

    after = [m for m in service.history if m.role is not Role.SYSTEM]
    assert [m.content for m in after] == [m.content for m in before if m.role is not Role.SYSTEM]


def test_set_reasoning_mode_does_not_create_a_new_chat(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")
    chat_id = service.active_session.id

    service.set_reasoning_mode(ReasoningMode.DEEP)

    assert service.active_session.id == chat_id
    assert len(repository.list_chats()) == 1


def test_set_reasoning_mode_does_not_alter_course(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.new_chat(course_id=course.id)
    service.send("hello")

    service.set_reasoning_mode(ReasoningMode.DEEP)

    assert service.active_session.course_id == course.id


def test_set_reasoning_mode_does_not_alter_title(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")
    service.rename_active_chat("My Title")

    service.set_reasoning_mode(ReasoningMode.DEEP)

    assert service.active_session.title == "My Title"


def test_reasoning_mode_and_teaching_mode_are_fully_independent(repository, course_repository):
    """Setting one never touches the other, in either direction or order."""
    service = make_service(repository, course_repository)
    service.send("hello")

    service.set_teaching_mode(TeachingMode.EXAM)
    service.set_reasoning_mode(ReasoningMode.DEEP)

    assert service.active_session.teaching_mode is TeachingMode.EXAM
    assert service.active_session.reasoning_mode is ReasoningMode.DEEP

    service.set_teaching_mode(TeachingMode.QUICK)
    assert service.active_session.reasoning_mode is ReasoningMode.DEEP  # untouched

    service.set_reasoning_mode(ReasoningMode.FAST)
    assert service.active_session.teaching_mode is TeachingMode.QUICK  # untouched


def test_reasoning_mode_applies_to_next_inference(repository, course_repository):
    """ChatService/ModelProvider receive the chat's current reasoning mode
    on every call — proven generically here (no Ollama dependency) via
    RecordingModel's received_reasoning_modes."""
    model = RecordingModel(reply="ack")
    service = SessionService(
        model=model, repository=repository, course_repository=course_repository,
        system_prompt="Baseline.",
    )
    service.send("hello")
    assert model.received_reasoning_modes[-1] is ReasoningMode.FAST

    service.set_reasoning_mode(ReasoningMode.DEEP)
    service.send("next message")

    assert model.received_reasoning_modes[-1] is ReasoningMode.DEEP


def test_rename_does_not_reset_reasoning_mode(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")
    service.set_reasoning_mode(ReasoningMode.DEEP)

    service.rename_active_chat("New Title")

    assert service.active_session.reasoning_mode is ReasoningMode.DEEP
    assert repository.get_chat(service.active_session.id).reasoning_mode is ReasoningMode.DEEP


def test_clear_does_not_reset_reasoning_mode(repository, course_repository):
    service = make_service(repository, course_repository)
    service.send("hello")
    service.set_reasoning_mode(ReasoningMode.DEEP)

    service.clear_active_chat()

    assert service.active_session.reasoning_mode is ReasoningMode.DEEP


def test_moving_chat_between_courses_does_not_change_reasoning_mode(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.send("hello")
    service.set_reasoning_mode(ReasoningMode.DEEP)

    service.move_active_chat_to_course(course.id)

    assert service.active_session.reasoning_mode is ReasoningMode.DEEP


def test_deleting_course_does_not_change_chat_reasoning_mode(repository, course_repository):
    course = course_repository.create_course("c1", "Physics", None, None, None)
    service = make_service(repository, course_repository)
    service.new_chat(course_id=course.id)
    service.send("hello")
    service.set_reasoning_mode(ReasoningMode.DEEP)

    course_repository.delete_course(course.id)
    service.sync_active_chat_course()

    assert service.active_session.reasoning_mode is ReasoningMode.DEEP


def test_reasoning_mode_persists_across_restart(repository, course_repository):
    service1 = make_service(repository, course_repository)
    service1.send("hello")
    service1.set_reasoning_mode(ReasoningMode.DEEP)

    service2 = make_service(repository, course_repository)

    assert service2.get_reasoning_mode() is ReasoningMode.DEEP


def test_different_chats_preserve_different_reasoning_modes(repository, course_repository):
    """Chat A -> Fast, Chat B -> Deep, Chat C -> Fast: changing one must
    never change the others, and reopening each restores its own — proving
    reasoning-mode isolation the same way teaching mode is proven above."""
    service = make_service(repository, course_repository)

    service.send("chat a")
    chat_a = service.active_session.id  # stays Fast (the default)

    service.new_chat()
    service.send("chat b")
    service.set_reasoning_mode(ReasoningMode.DEEP)
    chat_b = service.active_session.id

    service.new_chat()
    service.send("chat c")
    chat_c = service.active_session.id  # stays Fast

    service.open_chat(chat_a)
    assert service.get_reasoning_mode() is ReasoningMode.FAST
    service.open_chat(chat_b)
    assert service.get_reasoning_mode() is ReasoningMode.DEEP
    service.open_chat(chat_c)
    assert service.get_reasoning_mode() is ReasoningMode.FAST

    # Changing chat B's mode does not affect A or C.
    service.open_chat(chat_b)
    service.set_reasoning_mode(ReasoningMode.FAST)
    service.open_chat(chat_a)
    assert service.get_reasoning_mode() is ReasoningMode.FAST
    service.open_chat(chat_c)
    assert service.get_reasoning_mode() is ReasoningMode.FAST


def test_different_chats_preserve_different_reasoning_modes_across_restart(repository, course_repository):
    service1 = make_service(repository, course_repository)
    service1.send("chat a")
    chat_a = service1.active_session.id  # Fast (default)

    service1.new_chat()
    service1.send("chat b")
    service1.set_reasoning_mode(ReasoningMode.DEEP)
    chat_b = service1.active_session.id

    service2 = make_service(repository, course_repository)
    assert service2.open_chat(chat_a).reasoning_mode is ReasoningMode.FAST
    assert service2.open_chat(chat_b).reasoning_mode is ReasoningMode.DEEP
