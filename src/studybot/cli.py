"""Interactive terminal chat shell.

This is one interface on top of `StudyBotApp` / `ChatService`. It contains no
core logic of its own — it only reads input, dispatches commands, and prints
output.
"""

from __future__ import annotations

import logging

from studybot.app import StudyBotApp
from studybot.core.exceptions import StudyBotError
from studybot.core.messages import Role

logger = logging.getLogger(__name__)

_BANNER = "Study Bot\nLocal study assistant — Foundation Build\n\nType /help for commands."

_HELP_TEXT = """\
Available commands:
  /help     Show this message
  /history  Show the current conversation history
  /clear    Clear the conversation history
  /quit     Exit Study Bot"""

_PROMPT = "You > "


def run() -> int:
    """Run the interactive chat shell. Returns a process exit code."""
    app = StudyBotApp.from_env()
    print(_BANNER)

    while True:
        try:
            user_input = input(_PROMPT)
        except EOFError:
            print()
            print("Goodbye.")
            return 0
        except KeyboardInterrupt:
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
            reply = app.chat.send(text)
        except StudyBotError as exc:
            print(f"Error: {exc}")
            continue
        except Exception:
            logger.exception("Unexpected error while generating a response")
            print("Error: something went wrong. See logs for details.")
            continue

        print(f"Bot > {reply.content}")


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
