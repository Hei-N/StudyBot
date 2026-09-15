"""FastAPI dependency functions: transport-layer plumbing only.

These enforce authentication — they never touch course/chat/mode business
logic themselves. See `api/engine.py` for the `StudyBotApp` access
dependency (`get_engine`), which additionally has to worry about thread
affinity for the underlying SQLite connection.
"""

from __future__ import annotations

from fastapi import Header, Request

from studybot.api.auth import extract_bearer_token, token_matches
from studybot.api.errors import UNAUTHORIZED, ApiError


def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Raise `ApiError(401, UNAUTHORIZED, ...)` unless a valid
    `Authorization: Bearer <token>` header matches this process's token."""
    provided = extract_bearer_token(authorization)
    if not token_matches(provided, request.app.state.api_token):
        raise ApiError(401, UNAUTHORIZED, "Missing or invalid authentication token.")
