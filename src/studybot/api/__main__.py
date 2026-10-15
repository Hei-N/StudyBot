"""Entry point for ``python -m studybot.api`` and the ``studybot-server`` command.

Binds to 127.0.0.1 only; the host is deliberately not configurable.
See API_CONTRACT.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import uvicorn

from studybot.api.auth import resolve_startup_token
from studybot.api.server import create_app
from studybot.config.settings import Settings
from studybot.logging_config import configure_logging

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 8765
_HOST = "127.0.0.1"  # not configurable; see module docstring


def _configured_port() -> int:
    """Port from ``STUDYBOT_API_PORT``; 0 requests an OS-assigned port, which the
    startup handshake line reports.
    """
    raw = os.environ.get("STUDYBOT_API_PORT")
    if raw is None:
        return _DEFAULT_PORT
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"Invalid STUDYBOT_API_PORT {raw!r}; must be an integer.") from None


async def _serve() -> None:
    settings = Settings.from_env()
    configure_logging(settings)
    token = resolve_startup_token()
    app = create_app(settings=settings, token=token)

    config = uvicorn.Config(app, host=_HOST, port=_configured_port(), log_level="warning")
    if not config.loaded:
        config.load()
    server = uvicorn.Server(config)
    # Normally set in Server._serve(); we drive startup()/main_loop()/shutdown()
    # ourselves to print the bound port in between.
    server.lifespan = config.lifespan_class(config)

    with server.capture_signals():
        await server.startup()
        if server.should_exit:
            return
        actual_port = server.servers[0].sockets[0].getsockname()[1]
        _announce_ready(actual_port, token)
        await server.main_loop()
        await server.shutdown()


def _announce_ready(port: int, token: str) -> None:
    """Print one handshake line on stdout (deliberately not via ``logging``) so a
    launcher learns the bound port and token once at startup.

    Neither is persisted or logged.
    """
    print(
        json.dumps({"event": "studybot_api_ready", "host": _HOST, "port": port, "token": token}),
        flush=True,
    )


def main() -> None:
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
