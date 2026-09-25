"""Learning memory: durable, course-scoped learning information StudyBot
retains independently of raw chat history (Stage 6).

Chat history answers "what was said?"; learning memory answers "what
useful learning information should StudyBot retain?" The two are
deliberately separate systems — clearing or deleting a chat never deletes
a learning memory it produced (see `source_chat_id` on `LearningMemory` in
`storage.base`), and a learning memory is never a transcript or a summary
of a whole conversation, only a single, deliberately-created fact.

Pure domain data here — no I/O, no CLI/API/Flutter concepts — mirroring
`core.teaching_mode`/`core.reasoning_mode`'s shape: a stable, persisted
enum plus display metadata, so a UI can enumerate the catalog via
`all_kinds()` exactly like a mode picker does.

This is explicitly NOT a mastery/scoring engine: there is no numeric
weight, percentage, or aggregation anywhere in this module, by design.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MemoryKind(str, Enum):
    """Stable, persisted identifier for what *kind* of learning fact a
    memory records. Deliberately a closed, strict set — arbitrary
    free-text kinds are never allowed anywhere in the codebase."""

    UNDERSTANDS = "understands"
    NEEDS_REVIEW = "needs_review"
    MISCONCEPTION = "misconception"
    LEARNING_GOAL = "learning_goal"
    USEFUL_STRATEGY = "useful_strategy"


class MemoryStatus(str, Enum):
    """A memory's lifecycle state. Archiving is the default way to retire
    a memory (e.g. once superseded — see `opposes()` below); a memory is
    never physically deleted just because it's out of date. Hard deletion
    remains available as an explicit, separate operation
    (`LearningMemoryService.delete`)."""

    ACTIVE = "active"
    ARCHIVED = "archived"


DEFAULT_MEMORY_STATUS = MemoryStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class MemoryKindInfo:
    """Display metadata for one kind — what a memory-management UI needs,
    with natural-language wording (never a raw enum identifier)."""

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
    """Every kind's display metadata, in a stable order — the catalog a
    memory-creation UI should render."""
    return [_KIND_INFO[kind] for kind in MemoryKind]


def parse_memory_kind(value: str) -> MemoryKind:
    """Parse a stable identifier into a `MemoryKind`.

    Raises `ValueError` for anything else — callers are expected to catch
    this and show a clean message rather than letting it propagate as a
    crash. There are deliberately no aliases: the set of kinds is closed
    and small enough that a UI should always send the exact id.
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


# A topic's current learning state is modeled as two opposing "poles":
# having grasped it (`UNDERSTANDS`) versus still needing attention
# (`NEEDS_REVIEW`/`MISCONCEPTION`). `LEARNING_GOAL` and `USEFUL_STRATEGY`
# are not claims about current understanding at all, so they never oppose
# anything — a goal and a review note about the same topic can coexist.
_UNDERSTANDS_POLE = frozenset({MemoryKind.UNDERSTANDS})
_NEEDS_ATTENTION_POLE = frozenset({MemoryKind.NEEDS_REVIEW, MemoryKind.MISCONCEPTION})


def opposes(a: MemoryKind, b: MemoryKind) -> bool:
    """True if `a` and `b` represent opposite learning states for what is
    presumably the same topic (Stage 6's conflict/supersession policy —
    see `LearningMemoryService`). Used to decide when a newly (re)activated
    memory should archive an older, now-contradicted one rather than the
    two coexisting forever.
    """
    return (a in _UNDERSTANDS_POLE and b in _NEEDS_ATTENTION_POLE) or (
        a in _NEEDS_ATTENTION_POLE and b in _UNDERSTANDS_POLE
    )
