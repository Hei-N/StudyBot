"""``GET /api/v1/modes``: the teaching-mode catalog, derived from
``core.teaching_mode.all_modes()``.

Pure domain data, so no ``Engine`` dispatch is needed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from studybot.api.converters import mode_info_to_out
from studybot.api.dependencies import require_token
from studybot.api.schemas import ModeInfoOut
from studybot.core.teaching_mode import all_modes

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/modes", response_model=list[ModeInfoOut])
def list_modes() -> list[ModeInfoOut]:
    return [mode_info_to_out(info) for info in all_modes()]
