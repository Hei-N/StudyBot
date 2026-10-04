"""Interactive terminal chat shell.

This is one interface on top of `StudyBotApp` / `SessionService` /
`CourseService`. It contains no core logic of its own — it only reads
input, dispatches commands, and prints output. It does not know (and must
not import) anything Ollama- or SQLite-specific.
"""

from __future__ import annotations

import logging

from studybot.app import StudyBotApp
from studybot.core.exceptions import StudyBotError
from studybot.core.messages import Role
from studybot.core.reasoning_mode import all_modes as all_reasoning_modes
from studybot.core.reasoning_mode import get_mode_info as get_reasoning_mode_info
from studybot.core.reasoning_mode import parse_reasoning_mode
from studybot.core.teaching_mode import all_modes, get_mode_info, parse_teaching_mode
from studybot.models.base import ProviderStatus
from studybot.storage.base import ChatSession, Course

logger = logging.getLogger(__name__)

_HELP_TEXT = """\
Available commands:
  /help              Show this message
  /history           Show the active chat's conversation history
  /status            Show model provider connection/availability status
  /new               Start a new chat (in the active course, if any)
  /chats [all]       List chats in the active course/General, or all chats
  /open <id>         Switch to an existing chat (id or unique prefix)
  /rename <name>     Rename the active chat
  /clear             Remove the active chat's messages (asks to confirm)
  /delete            Delete the active chat entirely (asks to confirm)
  /mode              Show the active chat's teaching mode and all modes
  /mode <name>       Change the active chat's teaching mode
  /reasoning         Show the active chat's reasoning mode and all modes
  /reasoning <name>  Change the active chat's reasoning mode (fast|deep)
  /course new        Create a course and activate it
  /course list       List courses
  /course open <id>  Activate a course (id or unique prefix)
  /course info       Show the active course's details
  /course edit       Edit the active course's details
  /course delete     Delete the active course (asks to confirm; chats survive)
  /course leave      Leave the active course, back to General
  /chat course <id>  Move the active chat into a course
  /chat course none  Remove the active chat from its course (General)
  /quit              Exit Study Bot"""

_PROMPT = "You > "
_SHORT_ID_LENGTH = 8


def run() -> int:
    """Run the interactive chat shell. Returns a process exit code."""
    app = StudyBotApp.from_env()
    try:
        return _run_loop(app)
    finally:
        app.close()


def _run_loop(app: StudyBotApp) -> int:
    _print_banner(app)

    while True:
        try:
            user_input = input(_PROMPT)
        except (EOFError, KeyboardInterrupt):
            print()
            print("Goodbye.")
            return 0

        text = user_input.strip()
        if not text:
            continue

        if text.startswith("/"):
            if _handle_command(text, app):
                return 0
            continue

        try:
            _send_and_print(app, text)
        except StudyBotError as exc:
            print(f"Error: {exc}")
        except KeyboardInterrupt:
            print()
            print("Goodbye.")
            return 0
        except Exception:
            logger.exception("Unexpected error while generating a response")
            print("Error: something went wrong. See logs for details.")


def _print_banner(app: StudyBotApp) -> None:
    print("Study Bot")
    print("Local study assistant")
    print()
    print(f"Provider: {_display_provider_name(app)}")
    print(f"Model: {_display_model_name(app)}")
    course = _active_course(app)
    print(f"Course: {course.name if course else 'General'}")
    print(f"Chat: {_display_title(app.sessions.active_session)}")
    print(f"Mode: {get_mode_info(app.sessions.get_teaching_mode()).display_name}")
    print(f"Reasoning: {get_reasoning_mode_info(app.sessions.get_reasoning_mode()).display_name}")
    print()
    print("Type /help for commands.")


def _send_and_print(app: StudyBotApp, text: str) -> None:
    """Stream a reply to the terminal.

    The "Bot > " prefix is only printed once the first chunk actually
    arrives, so a failure before any content is produced shows a clean
    error line instead of a dangling empty prompt. If a failure happens
    after some content has streamed, that partial text stays visible
    followed by the error on its own line — it is never mistaken for a
    complete answer, and it is never persisted, because `SessionService`
    only writes an assistant message once `ChatService` records one.
    """
    prefix_printed = False
    try:
        for chunk in app.sessions.send_streaming(text):
            if not chunk:
                continue  # a progress signal (model still reasoning), not text
            if not prefix_printed:
                print("Bot > ", end="", flush=True)
                prefix_printed = True
            print(chunk, end="", flush=True)
    finally:
        if prefix_printed:
            print()


def _handle_command(command: str, app: StudyBotApp) -> bool:
    """Handle a slash command. Returns True if the shell should exit."""
    name, _, argument = command.partition(" ")
    argument = argument.strip()

    match name:
        case "/help":
            print(_HELP_TEXT)
        case "/clear":
            _clear_active_chat(app)
        case "/history":
            _print_history(app)
        case "/status":
            _print_status(app)
        case "/new":
            _new_chat(app)
        case "/chats":
            _print_chats(app, argument)
        case "/open":
            _open_chat(app, argument)
        case "/rename":
            _rename_active_chat(app, argument)
        case "/delete":
            _delete_active_chat(app)
        case "/mode":
            _handle_mode_command(app, argument)
        case "/reasoning":
            _handle_reasoning_command(app, argument)
        case "/course":
            _handle_course_command(app, argument)
        case "/chat":
            _handle_chat_command(app, argument)
        case "/quit":
            print("Goodbye.")
            return True
        case _:
            print(f"Unknown command: {name}. Type /help for a list of commands.")
    return False


def _print_history(app: StudyBotApp) -> None:
    # The system prompt is always present in `history` (it's re-seeded on
    # every new/cleared/reloaded chat) but is never shown to the user, so
    # emptiness must be judged after filtering it out — not before.
    messages = [m for m in app.sessions.history if m.role is not Role.SYSTEM]
    if not messages:
        print("(empty)")
        return

    for message in messages:
        label = "You" if message.role is Role.USER else "Bot"
        print(f"{label} > {message.content}")


def _print_status(app: StudyBotApp) -> None:
    try:
        status: ProviderStatus = app.sessions.get_status()
    except StudyBotError as exc:
        print(f"Error: {exc}")
        return

    print("Study Bot Status")
    print()
    print(f"Provider: {_display_name(status.provider_name)}")
    print(f"Server: {'Connected' if status.server_reachable else 'Unavailable'}")
    print(f"Model: {status.model_name}")
    if status.model_available is not None:
        print(f"Model available: {'Yes' if status.model_available else 'No'}")
    if status.detail:
        print(status.detail)


def _new_chat(app: StudyBotApp) -> None:
    session = app.sessions.new_chat()
    print(f"Started a new chat: {_display_title(session)}")


def _print_chats(app: StudyBotApp, argument: str) -> None:
    show_all = argument.strip().lower() == "all"
    active_course_id = app.sessions.active_session.course_id

    if show_all:
        chats = app.sessions.list_chats()
        header = "Chats (all)"
    elif active_course_id is not None:
        course = app.courses.get_course(active_course_id)
        chats = app.sessions.list_chats_in_course(active_course_id)
        header = f"{course.name if course else 'Course'} — Chats"
    else:
        chats = app.sessions.list_chats_in_course(None)
        header = "General — Chats"

    if not chats:
        print("No chats yet. Use /new to start one, or /chats all to see every chat.")
        return

    active_id = app.sessions.active_session.id
    print(header)
    print()
    for chat in chats:
        marker = "* " if chat.id == active_id else "  "
        print(f"{marker}{_short_id(chat.id)}  {_display_title(chat)}")


def _open_chat(app: StudyBotApp, argument: str) -> None:
    if not argument:
        print("Usage: /open <chat-id>")
        return
    try:
        session = app.sessions.open_chat(argument)
    except StudyBotError as exc:
        print(f"Error: {exc}")
        return
    print(f"Switched to: {_display_title(session)}")


def _rename_active_chat(app: StudyBotApp, argument: str) -> None:
    if not argument:
        print("Usage: /rename <new title>")
        return
    try:
        session = app.sessions.rename_active_chat(argument)
    except StudyBotError as exc:
        print(f"Error: {exc}")
        return
    print(f"Renamed chat to: {_display_title(session)}")


def _clear_active_chat(app: StudyBotApp) -> None:
    title = _display_title(app.sessions.active_session)
    if not _confirm(f"Clear all messages from '{title}'?"):
        print("Cancelled.")
        return
    app.sessions.clear_active_chat()
    print("Conversation history cleared.")


def _delete_active_chat(app: StudyBotApp) -> None:
    title = _display_title(app.sessions.active_session)
    if not _confirm(f"Delete chat '{title}' and all of its messages?"):
        print("Cancelled.")
        return
    app.sessions.delete_active_chat()
    print(f"Deleted '{title}'. Active chat: {_display_title(app.sessions.active_session)}")


# --- /mode -------------------------------------------------------------------------


def _handle_mode_command(app: StudyBotApp, argument: str) -> None:
    if not argument:
        _print_mode_status(app)
        return

    try:
        mode = parse_teaching_mode(argument)
    except ValueError:
        print(f"Unknown mode: {argument!r}. Type /mode to see available modes.")
        return

    app.sessions.set_teaching_mode(mode)
    print(f"Teaching mode changed to {get_mode_info(mode).display_name}.")


def _print_mode_status(app: StudyBotApp) -> None:
    current = get_mode_info(app.sessions.get_teaching_mode())
    print(f"Teaching mode: {current.display_name}")
    print()
    print("Available:")
    for info in all_modes():
        print(f"  {info.mode.value:<10} {info.description}")


# --- /reasoning --------------------------------------------------------------------


def _handle_reasoning_command(app: StudyBotApp, argument: str) -> None:
    if not argument:
        _print_reasoning_status(app)
        return

    try:
        mode = parse_reasoning_mode(argument)
    except ValueError:
        print(f"Unknown reasoning mode: {argument!r}. Type /reasoning to see available modes.")
        return

    app.sessions.set_reasoning_mode(mode)
    print(f"Reasoning mode changed to {get_reasoning_mode_info(mode).display_name}.")


def _print_reasoning_status(app: StudyBotApp) -> None:
    current = get_reasoning_mode_info(app.sessions.get_reasoning_mode())
    print(f"Reasoning mode: {current.display_name}")
    print()
    print("Available:")
    for info in all_reasoning_modes():
        print(f"  {info.mode.value:<10} {info.description}")


# --- /course ---------------------------------------------------------------------


def _handle_course_command(app: StudyBotApp, argument: str) -> None:
    sub, _, rest = argument.partition(" ")
    rest = rest.strip()

    match sub:
        case "new":
            _course_new(app)
        case "list":
            _course_list(app)
        case "open":
            _course_open(app, rest)
        case "info":
            _course_info(app)
        case "edit":
            _course_edit(app)
        case "delete":
            _course_delete(app)
        case "leave":
            _course_leave(app)
        case "":
            print("Usage: /course <new|list|open|info|edit|delete|leave>")
        case _:
            print(f"Unknown /course subcommand: {sub}")


def _course_new(app: StudyBotApp) -> None:
    answers = _prompt_fields(
        [
            ("name", "Course name: "),
            ("code", "Course code (optional): "),
            ("term", "Term (optional): "),
            ("description", "Description (optional): "),
        ]
    )
    if answers is None:
        print("Cancelled.")
        return

    try:
        course = app.courses.create_course(
            answers["name"],
            answers["code"] or None,
            answers["term"] or None,
            answers["description"] or None,
        )
    except StudyBotError as exc:
        print(f"Error: {exc}")
        return

    app.sessions.open_course_context(course.id)
    print(f"Created and activated course: {course.name}")


def _course_list(app: StudyBotApp) -> None:
    courses = app.courses.list_courses()
    if not courses:
        print("No courses yet. Use /course new to create one.")
        return

    active_course_id = app.sessions.active_session.course_id
    print("Courses")
    print()
    for course in courses:
        marker = "* " if course.id == active_course_id else "  "
        details = "   ".join(x for x in (course.code, course.term) if x)
        line = f"{marker}{_short_id(course.id)}  {course.name}"
        if details:
            line += f"   {details}"
        print(line)


def _course_open(app: StudyBotApp, argument: str) -> None:
    if not argument:
        print("Usage: /course open <id>")
        return
    try:
        course = app.courses.resolve_course(argument)
    except StudyBotError as exc:
        print(f"Error: {exc}")
        return
    session = app.sessions.open_course_context(course.id)
    print(f"Activated course: {course.name}")
    print(f"Chat: {_display_title(session)}")


def _course_info(app: StudyBotApp) -> None:
    course = _active_course(app)
    if course is None:
        print("No active course. (Course: General)")
        return

    print(course.name)
    print()
    if course.code:
        print(f"Code: {course.code}")
    if course.term:
        print(f"Term: {course.term}")
    if course.description:
        print(f"Description: {course.description}")
    print(f"Chats: {app.courses.count_chats(course.id)}")


def _course_edit(app: StudyBotApp) -> None:
    course = _active_course(app)
    if course is None:
        print("No active course to edit.")
        return

    print(f"Editing '{course.name}' (blank = keep current, - = clear optional field)")
    answers = _prompt_fields(
        [
            ("name", f"Name [{course.name}]: "),
            ("code", f"Code [{course.code or '(none)'}]: "),
            ("term", f"Term [{course.term or '(none)'}]: "),
            ("description", f"Description [{course.description or '(none)'}]: "),
        ]
    )
    if answers is None:
        print("Cancelled.")
        return

    new_name = answers["name"].strip() or course.name
    new_code = _resolve_editable_field(answers["code"], course.code)
    new_term = _resolve_editable_field(answers["term"], course.term)
    new_description = _resolve_editable_field(answers["description"], course.description)

    try:
        updated = app.courses.edit_course(course.id, new_name, new_code, new_term, new_description)
    except StudyBotError as exc:
        print(f"Error: {exc}")
        return

    app.sessions.sync_active_chat_course()
    print(f"Updated course: {updated.name}")


def _course_delete(app: StudyBotApp) -> None:
    course = _active_course(app)
    if course is None:
        print("No active course to delete.")
        return

    if not _confirm(
        f"Delete course '{course.name}'? Its chats will NOT be deleted. They will become General/unassigned."
    ):
        print("Cancelled.")
        return

    app.courses.delete_course(course.id)
    app.sessions.sync_active_chat_course()
    print(f"Deleted course '{course.name}'. Its chats are now General.")


def _course_leave(app: StudyBotApp) -> None:
    session = app.sessions.open_course_context(None)
    print(f"Left course. Chat: {_display_title(session)}")


def _resolve_editable_field(raw_input: str, current: str | None) -> str | None:
    stripped = raw_input.strip()
    if stripped == "":
        return current
    if stripped == "-":
        return None
    return stripped


# --- /chat -------------------------------------------------------------------------


def _handle_chat_command(app: StudyBotApp, argument: str) -> None:
    sub, _, rest = argument.partition(" ")
    rest = rest.strip()

    match sub:
        case "course":
            _chat_course(app, rest)
        case _:
            print("Usage: /chat course <course-id> | /chat course none")


def _chat_course(app: StudyBotApp, argument: str) -> None:
    if not argument:
        print("Usage: /chat course <course-id> | /chat course none")
        return

    target = None if argument.lower() == "none" else argument
    try:
        session = app.sessions.move_active_chat_to_course(target)
    except StudyBotError as exc:
        print(f"Error: {exc}")
        return

    if session.course_id is None:
        print("Current chat moved to General.")
    else:
        course = app.courses.get_course(session.course_id)
        print(f"Current chat moved to {course.name if course else session.course_id}.")


# --- shared helpers ------------------------------------------------------------------


def _prompt(text: str) -> str | None:
    """Read one line of input; returns None (instead of raising) on
    EOF/Ctrl+C so a multi-step interactive flow can cancel cleanly."""
    try:
        return input(text)
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def _prompt_fields(fields: list[tuple[str, str]]) -> dict[str, str] | None:
    """Prompt for each (key, prompt_text) pair in order; returns None if
    the user cancels (EOF/Ctrl+C) partway through."""
    answers: dict[str, str] = {}
    for key, prompt_text in fields:
        value = _prompt(prompt_text)
        if value is None:
            return None
        answers[key] = value.strip()
    return answers


def _confirm(prompt: str) -> bool:
    """Ask a yes/no question, defaulting to No on any non-'y' answer,
    including EOF/Ctrl+C (which cancel the action rather than exiting)."""
    answer = _prompt(f"{prompt} [y/N] ")
    if answer is None:
        return False
    return answer.strip().lower() in ("y", "yes")


def _active_course(app: StudyBotApp) -> Course | None:
    course_id = app.sessions.active_session.course_id
    return app.courses.get_course(course_id) if course_id else None


def _short_id(entity_id: str) -> str:
    return entity_id[:_SHORT_ID_LENGTH]


def _display_title(session: ChatSession) -> str:
    return session.title if session.title else "Untitled"


def _display_provider_name(app: StudyBotApp) -> str:
    return _display_name(app.settings.model_provider)


def _display_model_name(app: StudyBotApp) -> str:
    if app.settings.model_provider == "ollama":
        return app.settings.ollama_model
    return "mock"


def _display_name(provider_name: str) -> str:
    return {"mock": "Mock", "ollama": "Ollama"}.get(provider_name, provider_name)
