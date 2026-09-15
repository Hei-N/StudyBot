"""FastAPI application factory for the Study Bot engine API.

Builds exactly one `StudyBotApp` per server process (the same class the CLI
uses) and exposes it (bundled with its dedicated worker thread — see
`api/engine.py`) via `app.state.engine` for route handlers to call into —
see `api/dependencies.py`/`api/engine.py`. This module contains no course/
chat/mode business logic itself.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from studybot.api import websocket
from studybot.api.auth import resolve_startup_token
from studybot.api.engine import Engine
from studybot.api.errors import INTERNAL_ERROR, ApiError
from studybot.api.routes import chats, courses, health, modes
from studybot.api.version import API_PREFIX
from studybot.app import StudyBotApp
from studybot.config.settings import Settings

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, token: str | None = None) -> FastAPI:
    """Build the FastAPI app. `settings`/`token` are injection seams for
    tests — normal startup (`api/__main__.py`) leaves both to their
    environment-driven defaults."""
    resolved_settings = settings or Settings.from_env()
    resolved_token = resolve_startup_token(token)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        loop = asyncio.get_running_loop()
        # A single dedicated thread owns StudyBotApp (and its SQLite
        # connection) for this process's whole lifetime — see
        # api/engine.py's module docstring for why.
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="studybot-engine")
        studybot_app = await loop.run_in_executor(executor, StudyBotApp, resolved_settings)

        app.state.engine = Engine(studybot_app, executor)
        app.state.api_token = resolved_token
        logger.debug("API server ready (provider=%r)", resolved_settings.model_provider)
        try:
            yield
        finally:
            await loop.run_in_executor(executor, studybot_app.close)
            executor.shutdown(wait=True)

    app = FastAPI(title="Study Bot API", version="1", lifespan=lifespan)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(courses.router, prefix=API_PREFIX)
    app.include_router(chats.router, prefix=API_PREFIX)
    app.include_router(modes.router, prefix=API_PREFIX)
    app.include_router(websocket.router, prefix=API_PREFIX)

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Deliberately logs only the method/path (never a request body, so
        # never message/course content) plus the exception for developers —
        # the client only ever sees a generic, user-safe message.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"code": INTERNAL_ERROR, "message": "Something went wrong. See server logs for details."},
        )

    return app
