"""Safety guard for real-model verification scripts.

A verification script must use a disposable database, never the real default
data directory. ``STUDYBOT_DATA_DIR`` is the only setting that controls the
location (an unrecognized variable such as ``STUDYBOT_DB_PATH`` is ignored and
falls back to the real default), so scripts call ``assert_safe_for_verification``
before doing anything destructive and treat ``UnsafeVerificationEnvironmentError``
as a hard stop. ``scripts/check_verification_env.py`` wraps the same check.

The application itself never calls this.
"""

from __future__ import annotations

from studybot.config.settings import Settings, default_data_dir


class UnsafeVerificationEnvironmentError(RuntimeError):
    """The resolved data directory is, contains, or is contained by the real default
    data directory. Verification must stop; do not catch and continue.
    """


def assert_safe_for_verification(settings: Settings) -> None:
    """Raise ``UnsafeVerificationEnvironmentError`` unless ``settings.data_dir`` is
    clearly not the real default directory.

    Checks both directions (parent and child), so a path above or inside the
    default is also rejected.
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
