"""Safety guard for real-model verification scripts (Stage 6.2).

Every real-Ollama verification script written for this project needs a
fresh, disposable database — never the real default StudyBot data
directory. That property was silently violated for several stages:
`STUDYBOT_DB_PATH` (used throughout Stage 5.7 through 6.1's real-model
verification scripts, in this repository's own conversation history, not
committed code) is not a recognized setting — only `STUDYBOT_DATA_DIR` is
— so `Settings.from_env` silently ignored it and fell back to the real
default data directory every time. Several stages' "fresh database" real-
verification claims were, in fact, running against real accumulated local
data as a result.

This module exists so that mistake class can't recur silently: any
verification script — in-process (constructs `Settings` itself) or an
external shell script driving a `studybot-server` subprocess (see
`scripts/check_verification_env.py`, a thin CLI wrapper around this) —
should call `assert_safe_for_verification` before doing anything
destructive, and treat any resulting `UnsafeVerificationEnvironmentError`
as a hard stop, never a warning to route around.

This module has no purpose in normal application operation — the CLI and
API server never call it, and never need to. It exists purely for
verification/testing tooling.
"""

from __future__ import annotations

from studybot.config.settings import Settings, default_data_dir


class UnsafeVerificationEnvironmentError(RuntimeError):
    """Raised when a verification script's resolved data directory is (or
    contains, or is contained by) the real default StudyBot data
    directory. Never meant to be caught and silently ignored — a
    verification script hitting this should stop immediately and report
    it, not fall back to anything."""


def assert_safe_for_verification(settings: Settings) -> None:
    """Raise `UnsafeVerificationEnvironmentError` unless `settings.data_dir`
    is clearly *not* the real default StudyBot data directory.

    Checks equality in both directions (parent-of/child-of), not just
    exact equality, so a verification script that (say) accidentally
    points `STUDYBOT_DATA_DIR` at the real default directory's parent, or
    at a subdirectory inside it, is caught too — not just an exact path
    match.
    """
    real_default = default_data_dir().resolve()
    resolved = settings.data_dir.resolve()

    if resolved == real_default or real_default in resolved.parents or resolved in real_default.parents:
        raise UnsafeVerificationEnvironmentError(
            f"Refusing to proceed: the resolved data directory {resolved} is "
            f"(or contains, or is contained by) the real default StudyBot "
            f"data directory {real_default}. A verification script must "
            f"never run a destructive operation there. Set STUDYBOT_DATA_DIR "
            f"to a fresh, unique temporary directory instead — e.g. "
            f'`export STUDYBOT_DATA_DIR="$(mktemp -d)"` — and re-run.'
        )
