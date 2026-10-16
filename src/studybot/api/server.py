"""FastAPI application factory for the engine API.

Builds one ``StudyBotApp`` per server process (with its worker thread, see
``api/engine.py``) and exposes it via ``app.state.engine``. Contains no
business logic.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from studybot.api import websocket
from studybot.api.auth import resolve_startup_token
from studybot.api.engine import Engine
from studybot.api.ingest import PdfImporter
from studybot.api.errors import INTERNAL_ERROR, VALIDATION_ERROR, ApiError
from studybot.api.routes import chats, courses, health, library, memories, modes, reasoning
from studybot.api.version import API_PREFIX
from studybot.app import StudyBotApp
from studybot.config.settings import Settings
from studybot.core.ingest_staging import StagingArea
from studybot.core.pdf_extractor import PdfExtractor

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None, token: str | None = None, pdf_extractor: PdfExtractor | None = None
) -> FastAPI:
    """Build the FastAPI app. ``settings``, ``token`` and ``pdf_extractor`` are test seams."""
    resolved_settings = settings or Settings.from_env()
    resolved_token = resolve_startup_token(token)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        loop = asyncio.get_running_loop()
        # One dedicated thread owns StudyBotApp and its SQLite connection
        # (see api/engine.py).
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="studybot-engine")
        studybot_app = await loop.run_in_executor(executor, StudyBotApp, resolved_settings)

        app.state.engine = Engine(studybot_app, executor)
        staging = StagingArea(resolved_settings.data_dir / "ingest_staging")
        staging.ensure()
        staging.cleanup_orphans()
        # One worker: PDF hashing and extraction are bounded and never run on the SQLite thread.
        pdf_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="studybot-pdf")
        app.state.staging = staging
        app.state.pdf_importer = PdfImporter(app.state.engine, staging, pdf_extractor or PdfExtractor(), pdf_executor)
        app.state.api_token = resolved_token
        logger.debug("API server ready (provider=%r)", resolved_settings.model_provider)
        try:
            yield
        finally:
            await loop.run_in_executor(executor, studybot_app.close)
            pdf_executor.shutdown(wait=True)
            executor.shutdown(wait=True)

    app = FastAPI(title="Study Bot API", version="1", lifespan=lifespan)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(courses.router, prefix=API_PREFIX)
    app.include_router(chats.router, prefix=API_PREFIX)
    app.include_router(modes.router, prefix=API_PREFIX)
    app.include_router(reasoning.router, prefix=API_PREFIX)
    app.include_router(memories.router, prefix=API_PREFIX)
    app.include_router(library.router, prefix=API_PREFIX)
    app.include_router(websocket.router, prefix=API_PREFIX)

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # The default response echoes the offending input; for library requests that
        # could be an authorization payload, so those get a generic message.
        if request.url.path.startswith(f"{API_PREFIX}/library"):
            return JSONResponse(
                status_code=422, content={"code": VALIDATION_ERROR, "message": "The request was not valid."}
            )
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Log only the method and path (never request bodies) plus the exception;
        # the client gets a generic message.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"code": INTERNAL_ERROR, "message": "Something went wrong. See server logs for details."},
        )

    return app
