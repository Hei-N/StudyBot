"""Reasoning modes: how much inference-time "thinking" the model does before
answering.

Independent of ``core.teaching_mode``: teaching mode shapes instructional
behavior, reasoning mode shapes inference depth and latency, and a chat can use
any combination. Pure domain data, mirroring ``core.teaching_mode`` so a UI can
list the catalog via ``all_modes()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReasoningMode(str, Enum):
    """Stable, persisted identifier for how much reasoning the model does before answering."""

    FAST = "fast"
    DEEP = "deep"


DEFAULT_REASONING_MODE = ReasoningMode.FAST


@dataclass(frozen=True, slots=True)
class ReasoningModeInfo:
    """Display metadata for one mode."""

    mode: ReasoningMode
    display_name: str
    description: str


_MODE_INFO: dict[ReasoningMode, ReasoningModeInfo] = {
    ReasoningMode.FAST: ReasoningModeInfo(
        ReasoningMode.FAST, "Fast", "Answers without extended reasoning when the model supports it — faster."
    ),
    ReasoningMode.DEEP: ReasoningModeInfo(
        ReasoningMode.DEEP,
        "Deep Think",
        "Reasons through the problem before answering — slower, for harder questions.",
    ),
}


def get_mode_info(mode: ReasoningMode) -> ReasoningModeInfo:
    return _MODE_INFO[mode]


def all_modes() -> list[ReasoningModeInfo]:
    """Every mode's display metadata, in a stable order."""
    return [_MODE_INFO[mode] for mode in ReasoningMode]


def parse_reasoning_mode(value: str) -> ReasoningMode:
    """Parse a stable identifier into a ``ReasoningMode``. Raises ``ValueError`` otherwise."""
    normalized = value.strip().lower()
    try:
        return ReasoningMode(normalized)
    except ValueError:
        raise ValueError(f"Unknown reasoning mode: {value!r}") from None
