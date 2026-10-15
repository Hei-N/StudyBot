"""Teaching modes: how the assistant behaves in a chat.

A closed set rather than free-form strings, so a UI can list ``all_modes()`` to
build a picker. Pure domain data with no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TeachingMode(str, Enum):
    """Stable, persisted identifier for how a chat's assistant behaves."""

    TEACH = "teach"
    HOMEWORK = "homework"
    QUICK = "quick"
    PRACTICE = "practice"
    EXAM = "exam"


DEFAULT_TEACHING_MODE = TeachingMode.TEACH


@dataclass(frozen=True, slots=True)
class TeachingModeInfo:
    """Display metadata for one mode."""

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

# Short aliases for CLI convenience; not a general fuzzy matcher.
_ALIASES: dict[str, TeachingMode] = {
    "hw": TeachingMode.HOMEWORK,
    "qa": TeachingMode.QUICK,
}


def get_mode_info(mode: TeachingMode) -> TeachingModeInfo:
    return _MODE_INFO[mode]


def all_modes() -> list[TeachingModeInfo]:
    """Every mode's display metadata, in a stable order."""
    return [_MODE_INFO[mode] for mode in TeachingMode]


def parse_teaching_mode(value: str) -> TeachingMode:
    """Parse a stable identifier or short alias into a ``TeachingMode``.

    Raises ``ValueError`` for anything else.
    """
    normalized = value.strip().lower()
    try:
        return TeachingMode(normalized)
    except ValueError:
        pass
    if normalized in _ALIASES:
        return _ALIASES[normalized]
    raise ValueError(f"Unknown teaching mode: {value!r}")
