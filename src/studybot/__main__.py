"""Entry point for `python -m studybot` and the installed `studybot` command."""

from __future__ import annotations

import sys

from studybot.cli import run


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
