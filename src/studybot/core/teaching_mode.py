"""Teaching modes: how the assistant should behave in a given chat.

A strict, closed set rather than free-form strings, so callers can't drift
into typos and a future UI can enumerate `TeachingMode` (via `all_modes()`)
directly to populate a mode picker without duplicating this list anywhere
else. This module is pure domain data — no I/O, no CLI concepts, no model
provider knowledge — so it's reusable by the CLI today and by any future UI
without change.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TeachingMode(str, Enum):
    """Stable, persisted identifier for how a chat's assistant should behave."""

    TEACH = "teach"
    HOMEWORK = "homework"
    QUICK = "quick"
    PRACTICE = "practice"
    EXAM = "exam"


DEFAULT_TEACHING_MODE = TeachingMode.TEACH


@dataclass(frozen=True, slots=True)
class TeachingModeInfo:
    """Display metadata for one mode — what a mode picker (CLI today, a
    future GUI later) needs and nothing more."""

    mode: TeachingMode
    display_name: str
    description: str


_MODE_INFO: dict[TeachingMode, TeachingModeInfo] = {
    TeachingMode.TEACH: TeachingModeInfo(
        TeachingMode.TEACH, "Teach", "Step-by-step tutoring that builds understanding."
    ),
    TeachingMode.HOMEWORK: TeachingModeInfo(
        TeachingMode.HOMEWORK, "Homework", "Guided homework help; full solutions on request."
    ),
    TeachingMode.QUICK: TeachingModeInfo(
        TeachingMode.QUICK, "Quick Answer", "Direct, concise answers with minimal explanation."
    ),
    TeachingMode.PRACTICE: TeachingModeInfo(
        TeachingMode.PRACTICE, "Practice", "One practice question at a time, with feedback."
    ),
    TeachingMode.EXAM: TeachingModeInfo(
        TeachingMode.EXAM, "Exam", "Exam-style questions with no hints until you answer."
    ),
}

# A couple of short, unambiguous aliases for CLI convenience. Kept
# deliberately small — this is not a general alias/fuzzy-matching system.
_ALIASES: dict[str, TeachingMode] = {
    "hw": TeachingMode.HOMEWORK,
    "qa": TeachingMode.QUICK,
}


def get_mode_info(mode: TeachingMode) -> TeachingModeInfo:
    return _MODE_INFO[mode]


def all_modes() -> list[TeachingModeInfo]:
    """Every mode's display metadata, in a stable order — the catalog a
    mode picker (CLI or future GUI) should render."""
    return [_MODE_INFO[mode] for mode in TeachingMode]


def parse_teaching_mode(value: str) -> TeachingMode:
    """Parse a stable identifier or short alias into a `TeachingMode`.

    Raises `ValueError` for anything else — callers (the CLI today) are
    expected to catch this and show a clean message rather than letting it
    propagate as a crash.
    """
    normalized = value.strip().lower()
    try:
        return TeachingMode(normalized)
    except ValueError:
        pass
    if normalized in _ALIASES:
        return _ALIASES[normalized]
    raise ValueError(f"Unknown teaching mode: {value!r}")
