"""FastAPI dependencies for authentication. ``get_engine`` lives in ``api/engine.py``."""

from __future__ import annotations

from fastapi import Header, Request

from studybot.api.auth import extract_bearer_token, token_matches
from studybot.api.errors import UNAUTHORIZED, ApiError


def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Raise ``ApiError(401, UNAUTHORIZED, ...)`` unless a valid bearer token is supplied."""
    provided = extract_bearer_token(authorization)
    if not token_matches(provided, request.app.state.api_token):
        raise ApiError(401, UNAUTHORIZED, "Missing or invalid authentication token.")
