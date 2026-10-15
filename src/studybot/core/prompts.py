"""Centralized prompt text.

Kept separate from model providers so every backend gets the same baseline
behavior.
"""

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful local study assistant. Give accurate, clear answers "
    "and acknowledge uncertainty when appropriate."
)
