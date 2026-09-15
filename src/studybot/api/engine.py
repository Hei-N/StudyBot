"""Runs synchronous `StudyBotApp`/service calls on one dedicated thread.

`StudyBotApp` (like the rest of Study Bot, designed for the single-threaded
CLI) owns a single `sqlite3.Connection`, which Python's `sqlite3` module
ties to the thread that created it. FastAPI dispatches sync route handlers
to a worker *pool* — a different thread per call, sometimes concurrently —
so calling into `StudyBotApp` directly from a route handler intermittently
raises `sqlite3.ProgrammingError: SQLite objects created in a thread can
only be used in that same thread` (verified empirically). Routing every
call (including the `StudyBotApp` constructor itself, in `server.py`'s
lifespan) through one dedicated single-worker executor fixes this without
adding any concurrency-control code to the engine itself: only one call
ever runs at a time, on the one thread that owns the connection, exactly
mirroring the single-threaded CLI's own access pattern.
"""

from __future__ import annotations

import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

from fastapi import Request

from studybot.app import StudyBotApp

T = TypeVar("T")


class Engine:
    """Bundles the `StudyBotApp` instance with the executor its calls must
    run on. `engine.app` is safe to read directly for plain attributes
    (e.g. `engine.app.settings`); anything that touches a service or the
    database must go through `engine.call(...)`."""

    def __init__(self, app: StudyBotApp, executor: ThreadPoolExecutor) -> None:
        self.app = app
        self._executor = executor

    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        loop = asyncio.get_running_loop()
        bound = functools.partial(func, *args, **kwargs) if kwargs else func
        call_args = () if kwargs else args
        return await loop.run_in_executor(self._executor, bound, *call_args)


def get_engine(request: Request) -> Engine:
    return request.app.state.engine
