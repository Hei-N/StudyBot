"""``GET /api/v1/health``: engine and provider status.

Exposes nothing beyond what the CLI's ``/status`` command shows.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from studybot.api.dependencies import require_token
from studybot.api.engine import Engine, get_engine
from studybot.api.schemas import HealthOut
from studybot.api.version import API_VERSION

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/health", response_model=HealthOut)
async def get_health(engine: Engine = Depends(get_engine)) -> HealthOut:
    status = await engine.call(engine.app.sessions.get_status)
    settings = engine.app.settings
    model = settings.ollama_model if settings.model_provider == "ollama" else "mock"
    return HealthOut(
        api_version=API_VERSION,
        status="ok",
        provider=settings.model_provider,
        model=model,
        provider_reachable=status.server_reachable,
        model_available=status.model_available,
    )
