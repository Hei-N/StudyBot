"""Reasoning modes: how much inference-time "thinking" the model should do
before answering, in a given chat.

Deliberately independent of `core.teaching_mode`: teaching mode controls
*instructional* behavior (how the assistant explains things), while
reasoning mode controls *inference depth/latency* (whether the model spends
time on hidden chain-of-thought before producing visible content). A chat
can be in any combination of the two — Homework+Deep, Quick+Fast, etc. —
and changing one never touches the other.

Pure domain data — no I/O, no CLI concepts, no model provider knowledge —
mirroring `core.teaching_mode`'s shape exactly so both are equally easy for
a UI to enumerate via `all_modes()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReasoningMode(str, Enum):
    """Stable, persisted identifier for how much inference-time reasoning
    the model should do in a given chat before producing visible content."""

    FAST = "fast"
    DEEP = "deep"


DEFAULT_REASONING_MODE = ReasoningMode.FAST


@dataclass(frozen=True, slots=True)
class ReasoningModeInfo:
    """Display metadata for one mode — what a mode picker (CLI today, a
    future GUI later) needs and nothing more."""

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
    """Every mode's display metadata, in a stable order — the catalog a
    mode picker (CLI or future GUI) should render."""
    return [_MODE_INFO[mode] for mode in ReasoningMode]


def parse_reasoning_mode(value: str) -> ReasoningMode:
    """Parse a stable identifier into a `ReasoningMode`.

    Raises `ValueError` for anything else — callers are expected to catch
    this and show a clean message rather than letting it propagate as a
    crash.
    """
    normalized = value.strip().lower()
    try:
        return ReasoningMode(normalized)
    except ValueError:
        raise ValueError(f"Unknown reasoning mode: {value!r}") from None
