"""Stable, machine-readable API error codes.

Flutter (or any client) should switch on `code`, never parse `message` —
`message` is a human-readable, user-safe string for display, not a contract.
Python tracebacks never reach a client; `server.py`'s catch-all handler logs
unexpected exceptions server-side and returns `INTERNAL_ERROR` instead.
"""

from __future__ import annotations

CHAT_NOT_FOUND = "CHAT_NOT_FOUND"
CHAT_BUSY = "CHAT_BUSY"
COURSE_NOT_FOUND = "COURSE_NOT_FOUND"
MEMORY_NOT_FOUND = "MEMORY_NOT_FOUND"
MEMORY_CONFLICT = "MEMORY_CONFLICT"
INVALID_MODE = "INVALID_MODE"
INVALID_REASONING_MODE = "INVALID_REASONING_MODE"
INVALID_MEMORY_KIND = "INVALID_MEMORY_KIND"
INVALID_MEMORY_STATUS = "INVALID_MEMORY_STATUS"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
MODEL_ERROR = "MODEL_ERROR"
VALIDATION_ERROR = "VALIDATION_ERROR"
UNAUTHORIZED = "UNAUTHORIZED"
INTERNAL_ERROR = "INTERNAL_ERROR"


class ApiError(Exception):
    """Raised by route handlers to produce a structured error response.

    Route handlers translate domain exceptions (`SessionError`, `ModelError`,
    ...) into one of these with the appropriate HTTP status and stable
    `code` — that translation is transport-layer plumbing, not business
    logic, so it stays here rather than changing what the domain layer
    raises.
    """

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
