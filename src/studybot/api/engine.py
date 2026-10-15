"""Runs ``StudyBotApp`` calls on one dedicated thread.

``StudyBotApp`` owns a single ``sqlite3.Connection``, which Python ties to the
thread that created it. FastAPI runs sync handlers on a worker pool, so calling
the app directly intermittently raises ``sqlite3.ProgrammingError``. Routing
every call (including construction, in ``server.py``'s lifespan) through one
single-worker executor avoids that without any locking: one call runs at a
time, on the thread that owns the connection.
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
    """Bundles the ``StudyBotApp`` with the executor its calls must run on.

    Plain attributes (e.g. ``engine.app.settings``) can be read directly; anything
    touching a service or the database must go through ``engine.call(...)``.
    """

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
