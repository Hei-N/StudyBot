#!/usr/bin/env python3
"""Fail-fast preflight check for real-model verification scripts (Stage
6.2) — run this BEFORE starting a `studybot-server` process for
verification purposes, with the same environment (in particular
`STUDYBOT_DATA_DIR`) you're about to launch it with:

    export STUDYBOT_DATA_DIR="$(mktemp -d -t studybot_verify)"
    python3 scripts/check_verification_env.py || exit 1
    STUDYBOT_MODEL_PROVIDER=ollama studybot-server &

`STUDYBOT_DB_PATH` is NOT a recognized setting (only `STUDYBOT_DATA_DIR`
is) — a mistake made throughout this project's own Stage 5.7-6.1
real-verification scripts, which silently fell back to the real default
data directory as a result. This script exists so that mistake, or any
variant of it, is caught before it can touch real data, not after.

Exits 0 (and prints the resolved, confirmed-safe database path) if the
environment resolves to somewhere other than the real default StudyBot
data directory. Exits 1 (and prints nothing that looks like a green
light) otherwise — including when `STUDYBOT_DATA_DIR` is unset entirely,
since that also resolves to the real default.
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
