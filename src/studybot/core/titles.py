"""Deterministic, local chat-title generation (no model call).

Collapses whitespace and truncates on a word boundary; the user can rename a
chat afterward.
"""

from __future__ import annotations

_MAX_TITLE_LENGTH = 40
_FALLBACK_TITLE = "Untitled"


def generate_title(first_message: str) -> str:
    """Derive a short title from a chat's first user message."""
    normalized = " ".join(first_message.split())
    if not normalized:
        return _FALLBACK_TITLE

    if len(normalized) <= _MAX_TITLE_LENGTH:
        return normalized

    truncated = normalized[:_MAX_TITLE_LENGTH]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated.rstrip() + "…"
