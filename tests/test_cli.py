import pytest

from studybot import cli
from studybot.app import StudyBotApp
from studybot.config.settings import Settings
from studybot.core.reasoning_mode import ReasoningMode
from studybot.core.teaching_mode import TeachingMode
from studybot.storage.base import ChatSession


@pytest.fixture
def app(tmp_path):
    settings = Settings.from_env(
        env={"STUDYBOT_MODEL_PROVIDER": "mock", "STUDYBOT_DATA_DIR": str(tmp_path)}
    )
    application = StudyBotApp(settings)
    yield application
    application.close()


def feed_input(monkeypatch, lines):
    """Make consecutive `input()` calls return each line in turn."""
    remaining = iter(lines)
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: next(remaining))


# --- pure helpers ------------------------------------------------------------------


def test_resolve_editable_field_blank_keeps_current():
    assert cli._resolve_editable_field("", "current") == "current"
    assert cli._resolve_editable_field("   ", "current") == "current"


def test_resolve_editable_field_dash_clears():
    assert cli._resolve_editable_field("-", "current") is None


def test_resolve_editable_field_new_value_overrides():
    assert cli._resolve_editable_field("new value", "current") == "new value"


def test_display_title_shows_untitled_for_none():
    session = ChatSession(
        id="x", title=None, course_id=None, teaching_mode=TeachingMode.TEACH,
        reasoning_mode=ReasoningMode.FAST, created_at="t", updated_at="t",
    )
    assert cli._display_title(session) == "Untitled"


def test_display_title_shows_actual_title():
    session = ChatSession(
        id="x", title="My Chat", course_id=None, teaching_mode=TeachingMode.TEACH,
        reasoning_mode=ReasoningMode.FAST, created_at="t", updated_at="t",
    )
    assert cli._display_title(session) == "My Chat"


def test_short_id_truncates():
    assert cli._short_id("abcdefghijklmnop") == "abcdefgh"


# --- /course new ---------------------------------------------------------------------


def test_course_new_creates_and_activates_course(app, monkeypatch, capsys):
    feed_input(monkeypatch, ["University Physics I", "PHY 215", "Fall 2026", "Mechanics"])

    cli._course_new(app)

    course = app.sessions.active_session.course_id
    assert app.courses.get_course(course).name == "University Physics I"
    assert "Created and activated course: University Physics I" in capsys.readouterr().out


def test_course_new_with_optional_fields_blank(app, monkeypatch, capsys):
    feed_input(monkeypatch, ["Calculus III", "", "", ""])

    cli._course_new(app)

    course_id = app.sessions.active_session.course_id
    course = app.courses.get_course(course_id)
    assert course.code is None
    assert course.term is None
    assert course.description is None


def test_course_new_cancelled_on_eof(app, monkeypatch, capsys):
    def raise_eof(*args, **kwargs):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    cli._course_new(app)

    assert app.courses.list_courses() == []
    assert "Cancelled." in capsys.readouterr().out


def test_course_new_rejects_empty_name(app, monkeypatch, capsys):
    feed_input(monkeypatch, ["   ", "", "", ""])

    cli._course_new(app)

    assert app.courses.list_courses() == []
    assert "Error:" in capsys.readouterr().out


# --- /course edit ----------------------------------------------------------------------


def test_course_edit_blank_keeps_dash_clears(app, monkeypatch, capsys):
    course = app.courses.create_course("Physics", "PHY 101", "Spring", "Old desc")
    app.sessions.open_course_context(course.id)

    feed_input(monkeypatch, ["", "PHY 102", "", "-"])
    cli._course_edit(app)

    updated = app.courses.get_course(course.id)
    assert updated.name == "Physics"  # kept
    assert updated.code == "PHY 102"  # changed
    assert updated.term == "Spring"  # kept
    assert updated.description is None  # cleared


def test_course_edit_with_no_active_course(app, capsys):
    cli._course_edit(app)

    assert "No active course" in capsys.readouterr().out


# --- /course delete --------------------------------------------------------------------


def test_course_delete_requires_confirmation(app, monkeypatch, capsys):
    course = app.courses.create_course("Physics")
    app.sessions.open_course_context(course.id)
    app.sessions.send("hello")
    chat_id = app.sessions.active_session.id

    feed_input(monkeypatch, ["n"])
    cli._course_delete(app)

    assert app.courses.get_course(course.id) is not None
    assert "Cancelled." in capsys.readouterr().out

    feed_input(monkeypatch, ["y"])
    cli._course_delete(app)

    assert app.courses.get_course(course.id) is None
    assert app.sessions.active_session.id == chat_id  # stayed on the same chat
    assert app.sessions.active_session.course_id is None


# --- /chats ------------------------------------------------------------------------------


def test_print_chats_filters_by_active_course(app, capsys):
    course = app.courses.create_course("Physics")
    app.sessions.open_course_context(course.id)
    app.sessions.send("physics question")
    app.sessions.open_course_context(None)
    app.sessions.send("general question")

    cli._print_chats(app, "")
    general_output = capsys.readouterr().out
    assert "general question" in general_output
    assert "physics question" not in general_output

    app.sessions.open_course_context(course.id)
    cli._print_chats(app, "")
    course_output = capsys.readouterr().out
    assert "physics question" in course_output
    assert "general question" not in course_output


def test_print_chats_all_shows_everything(app, capsys):
    course = app.courses.create_course("Physics")
    app.sessions.open_course_context(course.id)
    app.sessions.send("physics question")
    app.sessions.open_course_context(None)
    app.sessions.send("general question")

    cli._print_chats(app, "all")

    output = capsys.readouterr().out
    assert "physics question" in output
    assert "general question" in output


# --- /chat course ------------------------------------------------------------------------


def test_chat_course_moves_active_chat(app, capsys):
    course = app.courses.create_course("Physics")
    app.sessions.send("hello")

    cli._chat_course(app, course.id)

    assert app.sessions.active_session.course_id == course.id
    assert "Current chat moved to Physics." in capsys.readouterr().out


def test_chat_course_none_unassigns(app, capsys):
    course = app.courses.create_course("Physics")
    app.sessions.open_course_context(course.id)
    app.sessions.send("hello")

    cli._chat_course(app, "none")

    assert app.sessions.active_session.course_id is None
    assert "Current chat moved to General." in capsys.readouterr().out


def test_chat_course_unknown_course_shows_error(app, capsys):
    app.sessions.send("hello")

    cli._chat_course(app, "does-not-exist")

    assert "Error:" in capsys.readouterr().out


# --- /mode -------------------------------------------------------------------------


def test_mode_status_shows_current_and_available_modes(app, capsys):
    cli._handle_mode_command(app, "")

    output = capsys.readouterr().out
    assert "Teaching mode: Teach" in output
    assert "teach" in output
    assert "homework" in output
    assert "quick" in output
    assert "practice" in output
    assert "exam" in output


def test_mode_teach(app, capsys):
    app.sessions.set_teaching_mode(TeachingMode.EXAM)

    cli._handle_mode_command(app, "teach")

    assert app.sessions.get_teaching_mode() is TeachingMode.TEACH
    assert "Teaching mode changed to Teach." in capsys.readouterr().out


def test_mode_homework(app, capsys):
    cli._handle_mode_command(app, "homework")

    assert app.sessions.get_teaching_mode() is TeachingMode.HOMEWORK
    assert "Teaching mode changed to Homework." in capsys.readouterr().out


def test_mode_quick(app, capsys):
    cli._handle_mode_command(app, "quick")

    assert app.sessions.get_teaching_mode() is TeachingMode.QUICK
    assert "Teaching mode changed to Quick Answer." in capsys.readouterr().out


def test_mode_practice(app, capsys):
    cli._handle_mode_command(app, "practice")

    assert app.sessions.get_teaching_mode() is TeachingMode.PRACTICE
    assert "Teaching mode changed to Practice." in capsys.readouterr().out


def test_mode_exam(app, capsys):
    cli._handle_mode_command(app, "exam")

    assert app.sessions.get_teaching_mode() is TeachingMode.EXAM
    assert "Teaching mode changed to Exam." in capsys.readouterr().out


def test_mode_invalid_shows_clean_error(app, capsys):
    cli._handle_mode_command(app, "not-a-real-mode")

    assert app.sessions.get_teaching_mode() is TeachingMode.TEACH  # unchanged
    output = capsys.readouterr().out
    assert "Unknown mode" in output


def test_mode_change_does_not_add_history_message(app, capsys):
    app.sessions.send("hello")
    before = len(app.sessions.history)

    cli._handle_mode_command(app, "homework")

    assert len(app.sessions.history) == before


# --- /reasoning --------------------------------------------------------------------


def test_reasoning_status_shows_current_and_available_modes(app, capsys):
    cli._handle_reasoning_command(app, "")

    output = capsys.readouterr().out
    assert "Reasoning mode: Fast" in output
    assert "fast" in output
    assert "deep" in output


def test_reasoning_deep(app, capsys):
    cli._handle_reasoning_command(app, "deep")

    assert app.sessions.get_reasoning_mode() is ReasoningMode.DEEP
    assert "Reasoning mode changed to Deep Think." in capsys.readouterr().out


def test_reasoning_fast(app, capsys):
    app.sessions.set_reasoning_mode(ReasoningMode.DEEP)

    cli._handle_reasoning_command(app, "fast")

    assert app.sessions.get_reasoning_mode() is ReasoningMode.FAST
    assert "Reasoning mode changed to Fast." in capsys.readouterr().out


def test_reasoning_invalid_shows_clean_error(app, capsys):
    cli._handle_reasoning_command(app, "not-a-real-mode")

    assert app.sessions.get_reasoning_mode() is ReasoningMode.FAST  # unchanged
    output = capsys.readouterr().out
    assert "Unknown reasoning mode" in output


def test_reasoning_change_does_not_affect_teaching_mode(app, capsys):
    app.sessions.set_teaching_mode(TeachingMode.HOMEWORK)

    cli._handle_reasoning_command(app, "deep")

    assert app.sessions.get_teaching_mode() is TeachingMode.HOMEWORK
    assert app.sessions.get_reasoning_mode() is ReasoningMode.DEEP


def test_reasoning_change_does_not_add_history_message(app, capsys):
    app.sessions.send("hello")
    before = len(app.sessions.history)

    cli._handle_reasoning_command(app, "deep")

    assert len(app.sessions.history) == before


def test_banner_shows_reasoning_mode(app, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: (_ for _ in ()).throw(EOFError()))

    cli._run_loop(app)

    assert "Reasoning: Fast" in capsys.readouterr().out
