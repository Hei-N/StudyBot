"""Interactive terminal chat shell.

This is one interface on top of `StudyBotApp` / `SessionService`. It
contains no core logic of its own — it only reads input, dispatches
commands, and prints output. It does not know (and must not import)
anything Ollama- or SQLite-specific.
"""

from __future__ import annotations

import logging

from studybot.app import StudyBotApp
from studybot.core.exceptions import StudyBotError
from studybot.core.messages import Role
from studybot.models.base import ProviderStatus
from studybot.storage.base import ChatSession

logger = logging.getLogger(__name__)

_HELP_TEXT = """\
Available commands:
  /help          Show this message
  /history       Show the active chat's conversation history
  /status        Show model provider connection/availability status
  /new           Start a new chat
  /chats         List saved chats
  /open <id>     Switch to an existing chat (id or unique prefix)
  /rename <name> Rename the active chat
  /clear         Remove the active chat's messages (asks to confirm)
  /delete        Delete the active chat entirely (asks to confirm)
  /quit          Exit Study Bot"""

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
    print(f"Chat: {_display_title(app.sessions.active_session)}")
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
            _print_chats(app)
        case "/open":
            _open_chat(app, argument)
        case "/rename":
            _rename_active_chat(app, argument)
        case "/delete":
            _delete_active_chat(app)
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


def _print_chats(app: StudyBotApp) -> None:
    chats = app.sessions.list_chats()
    if not chats:
        print("No saved chats yet.")
        return

    active_id = app.sessions.active_session.id
    print("Chats")
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


def _confirm(prompt: str) -> bool:
    """Ask a yes/no question, defaulting to No on any non-'y' answer,
    including EOF/Ctrl+C (which cancel the action rather than exiting)."""
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


def _short_id(chat_id: str) -> str:
    return chat_id[:_SHORT_ID_LENGTH]


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
