"""Per-process API authentication.

A random token is generated once per server process (never persisted or
logged) and must accompany every request as ``Authorization: Bearer <token>``.
This is not a user-account system: one token, valid for the process lifetime.
"""

from __future__ import annotations

import os
import secrets

_ENV_TOKEN_OVERRIDE = "STUDYBOT_API_TOKEN"


def resolve_startup_token(explicit: str | None = None) -> str:
    """Choose the token for this process: an explicit value (tests), then
    ``STUDYBOT_API_TOKEN``, otherwise a new random one.
    """
    if explicit is not None:
        return explicit
    env_token = os.environ.get(_ENV_TOKEN_OVERRIDE)
    if env_token:
        return env_token
    return secrets.token_urlsafe(32)


def extract_bearer_token(authorization_header: str | None) -> str | None:
    """Return the token from an ``Authorization: Bearer <token>`` header, or None if
    it is missing or malformed.
    """
    if authorization_header is None:
        return None
    scheme, _, value = authorization_header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value


def token_matches(provided: str | None, expected: str) -> bool:
    """Constant-time comparison, to avoid leaking token bytes through timing."""
    if provided is None:
        return False
    return secrets.compare_digest(provided, expected)
