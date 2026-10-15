"""Learning-memory domain types: kinds, statuses and display metadata.

A learning memory is a durable, course-scoped fact (e.g. "needs review:
vector components") retained independently of chat history; clearing a chat
never deletes the memories it produced. This is not a mastery or scoring
system: there are no weights or percentages.

Pure domain data with no I/O, mirroring ``core.teaching_mode`` so a UI can
list the catalog via ``all_kinds()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MemoryKind(str, Enum):
    """The kind of learning fact a memory records. A closed set; free-text kinds are not allowed.
    """

    UNDERSTANDS = "understands"
    NEEDS_REVIEW = "needs_review"
    MISCONCEPTION = "misconception"
    LEARNING_GOAL = "learning_goal"
    USEFUL_STRATEGY = "useful_strategy"


class MemoryStatus(str, Enum):
    """A memory's lifecycle state.

    Archiving is the normal way to retire a memory; hard deletion is a separate,
    explicit operation (``LearningMemoryService.delete``).
    """

    ACTIVE = "active"
    ARCHIVED = "archived"


DEFAULT_MEMORY_STATUS = MemoryStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class MemoryKindInfo:
    """Display metadata for one kind."""

    kind: MemoryKind
    display_name: str
    description: str


_KIND_INFO: dict[MemoryKind, MemoryKindInfo] = {
    MemoryKind.UNDERSTANDS: MemoryKindInfo(
        MemoryKind.UNDERSTANDS, "Understands", "The student has shown they understand this."
    ),
    MemoryKind.NEEDS_REVIEW: MemoryKindInfo(
        MemoryKind.NEEDS_REVIEW, "Needs review", "The student should revisit this before moving on."
    ),
    MemoryKind.MISCONCEPTION: MemoryKindInfo(
        MemoryKind.MISCONCEPTION,
        "Misconception",
        "A recurring mistaken belief worth gently correcting, not just a review topic.",
    ),
    MemoryKind.LEARNING_GOAL: MemoryKindInfo(
        MemoryKind.LEARNING_GOAL, "Goal", "Something the student wants to work toward."
    ),
    MemoryKind.USEFUL_STRATEGY: MemoryKindInfo(
        MemoryKind.USEFUL_STRATEGY,
        "Helpful approach",
        "An explanation or strategy that worked well for this student before.",
    ),
}


def get_kind_info(kind: MemoryKind) -> MemoryKindInfo:
    return _KIND_INFO[kind]


def all_kinds() -> list[MemoryKindInfo]:
    """Every kind's display metadata, in a stable order."""
    return [_KIND_INFO[kind] for kind in MemoryKind]


def parse_memory_kind(value: str) -> MemoryKind:
    """Parse a stable identifier into a ``MemoryKind``.

    Raises ``ValueError`` for anything else; there are no aliases.
    """
    normalized = value.strip().lower()
    try:
        return MemoryKind(normalized)
    except ValueError:
        raise ValueError(f"Unknown learning memory kind: {value!r}") from None


def parse_memory_status(value: str) -> MemoryStatus:
    """Like `parse_memory_kind`, for the `status` filter/field."""
    normalized = value.strip().lower()
    try:
        return MemoryStatus(normalized)
    except ValueError:
        raise ValueError(f"Unknown learning memory status: {value!r}") from None


# A topic is either grasped (UNDERSTANDS) or needs attention (NEEDS_REVIEW,
# MISCONCEPTION). LEARNING_GOAL and USEFUL_STRATEGY make no claim about
# current understanding, so they never oppose anything.
_UNDERSTANDS_POLE = frozenset({MemoryKind.UNDERSTANDS})
_NEEDS_ATTENTION_POLE = frozenset({MemoryKind.NEEDS_REVIEW, MemoryKind.MISCONCEPTION})


def opposes(a: MemoryKind, b: MemoryKind) -> bool:
    """True if ``a`` and ``b`` are opposite learning states for the same topic, so
    activating one should archive the other.
    """
    return (a in _UNDERSTANDS_POLE and b in _NEEDS_ATTENTION_POLE) or (
        a in _NEEDS_ATTENTION_POLE and b in _UNDERSTANDS_POLE
    )
