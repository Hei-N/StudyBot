"""``GET /api/v1/reasoning-modes``: the reasoning-mode catalog, derived from
``core.reasoning_mode.all_modes()``.

Pure domain data, so no ``Engine`` dispatch is needed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from studybot.api.converters import reasoning_mode_info_to_out
from studybot.api.dependencies import require_token
from studybot.api.schemas import ModeInfoOut
from studybot.core.reasoning_mode import all_modes

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/reasoning-modes", response_model=list[ModeInfoOut])
def list_reasoning_modes() -> list[ModeInfoOut]:
    return [reasoning_mode_info_to_out(info) for info in all_modes()]
