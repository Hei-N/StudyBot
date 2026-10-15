"""Logging setup.

Quiet by default, with verbosity set by ``STUDYBOT_LOG_LEVEL``. Conversation
content and other personal data are never logged.
"""

from __future__ import annotations

import logging

from studybot.config.settings import Settings

_CONSOLE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def configure_logging(settings: Settings) -> None:
    """Configure the root `studybot` logger. Safe to call more than once."""
    root = logging.getLogger("studybot")
    root.setLevel(settings.log_level_int)
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(handler)

    # Don't let messages bubble up to a root logger some other tool configured.
    root.propagate = False
