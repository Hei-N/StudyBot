"""Centralized prompt text.

Kept separate from any model provider so every backend (mock, Ollama, future
providers) gives the user the same baseline Study Bot behavior. This is
intentionally minimal for Stage 2 — the fuller tutor personality is later
work.
"""

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful local study assistant. Give accurate, clear answers "
    "and acknowledge uncertainty when appropriate."
)
