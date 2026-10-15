#!/usr/bin/env python3
"""Preflight check for real-model verification: run before starting
``studybot-server`` with the same environment.

    export STUDYBOT_DATA_DIR="$(mktemp -d -t studybot_verify)"
    python3 scripts/check_verification_env.py || exit 1
    STUDYBOT_MODEL_PROVIDER=ollama studybot-server &

``STUDYBOT_DATA_DIR`` is the only variable that selects the database location;
an unrecognized one such as ``STUDYBOT_DB_PATH`` is ignored and falls back to
the real default directory. Exits 0 and prints the resolved database path if it
is safe, 1 otherwise (including when ``STUDYBOT_DATA_DIR`` is unset).
"""

from __future__ import annotations

import sys

from studybot.config.settings import Settings
from studybot.config.verification_guard import UnsafeVerificationEnvironmentError, assert_safe_for_verification


def main() -> int:
    settings = Settings.from_env()  # reads the real environment, exactly like studybot-server will

    try:
        assert_safe_for_verification(settings)
    except UnsafeVerificationEnvironmentError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 1

    print(f"OK: verification database path is {settings.database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
