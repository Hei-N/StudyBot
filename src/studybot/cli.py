"""Interactive terminal chat shell.

This is one interface on top of `StudyBotApp` / `ChatService`. It contains no
core logic of its own — it only reads input, dispatches commands, and prints
output. It does not know (and must not import) anything Ollama-specific.
"""

from __future__ import annotations

import logging

from studybot.app import StudyBotApp
from studybot.core.exceptions import StudyBotError
from studybot.core.messages import Role
from studybot.models.base import ProviderStatus

logger = logging.getLogger(__name__)

_HELP_TEXT = """\
Available commands:
  /help     Show this message
  /history  Show the current conversation history
  /status   Show model provider connection/availability status
  /clear    Clear the conversation history
  /quit     Exit Study Bot"""

_PROMPT = "You > "


def run() -> int:
    """Run the interactive chat shell. Returns a process exit code."""
    app = StudyBotApp.from_env()
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
    print()
    print("Type /help for commands.")


def _send_and_print(app: StudyBotApp, text: str) -> None:
    """Stream a reply to the terminal.

    The "Bot > " prefix is only printed once the first chunk actually
    arrives, so a failure before any content is produced shows a clean
    error line instead of a dangling empty prompt. If a failure happens
    after some content has streamed, that partial text stays visible
    followed by the error on its own line — it is never mistaken for a
    complete answer because `ChatService` only records history on success.
    """
    prefix_printed = False
    try:
        for chunk in app.chat.send_streaming(text):
            if not prefix_printed:
                print("Bot > ", end="", flush=True)
                prefix_printed = True
            print(chunk, end="", flush=True)
    finally:
        if prefix_printed:
            print()


def _handle_command(command: str, app: StudyBotApp) -> bool:
    """Handle a slash command. Returns True if the shell should exit."""
    match command:
        case "/help":
            print(_HELP_TEXT)
        case "/clear":
            app.chat.clear()
            print("Conversation history cleared.")
        case "/history":
            _print_history(app)
        case "/status":
            _print_status(app)
        case "/quit":
            print("Goodbye.")
            return True
        case _:
            print(f"Unknown command: {command}. Type /help for a list of commands.")
    return False


def _print_history(app: StudyBotApp) -> None:
    history = app.chat.history
    if not history:
        print("(empty)")
        return

    for message in history:
        if message.role is Role.SYSTEM:
            continue
        label = "You" if message.role is Role.USER else "Bot"
        print(f"{label} > {message.content}")


def _print_status(app: StudyBotApp) -> None:
    try:
        status: ProviderStatus = app.chat.get_status()
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


def _display_provider_name(app: StudyBotApp) -> str:
    return _display_name(app.settings.model_provider)


def _display_model_name(app: StudyBotApp) -> str:
    if app.settings.model_provider == "ollama":
        return app.settings.ollama_model
    return "mock"


def _display_name(provider_name: str) -> str:
    return {"mock": "Mock", "ollama": "Ollama"}.get(provider_name, provider_name)
