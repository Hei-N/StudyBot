"""Per-process API authentication.

A high-entropy token is generated once per server process (never persisted,
never logged, never put in a URL) and must be supplied by every request via
`Authorization: Bearer <token>`. This is deliberately not a user-account
system — there is exactly one token, valid for exactly this process's
lifetime, suitable for a desktop app launching its own local engine.
"""

from __future__ import annotations

import os
import secrets

_ENV_TOKEN_OVERRIDE = "STUDYBOT_API_TOKEN"


def resolve_startup_token(explicit: str | None = None) -> str:
    """Decide the token for this process.

    Precedence: an explicit value (tests constructing the app directly) >
    the `STUDYBOT_API_TOKEN` environment variable (a deliberate development
    hook for injecting a known token) > a freshly generated random one.
    """
    if explicit is not None:
        return explicit
    env_token = os.environ.get(_ENV_TOKEN_OVERRIDE)
    if env_token:
        return env_token
    return secrets.token_urlsafe(32)


def extract_bearer_token(authorization_header: str | None) -> str | None:
    """Pull the token out of an `Authorization: Bearer <token>` header
    value, or None if the header is missing/malformed."""
    if authorization_header is None:
        return None
    scheme, _, value = authorization_header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value


def token_matches(provided: str | None, expected: str) -> bool:
    """Constant-time comparison — avoids leaking token bytes via timing."""
    if provided is None:
        return False
    return secrets.compare_digest(provided, expected)
