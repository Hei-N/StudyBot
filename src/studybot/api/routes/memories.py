"""Learning memory endpoints (Stage 6) — thin translation onto
`LearningMemoryService`.

No memory business logic (validation, duplicate/conflict policy, context
composition) lives here — see `core.memory_service.LearningMemoryService`.
Every route addresses its memory purely by `memory_id`, exactly like the
explicit-by-id chat operations added in Stage 5.8 — there is no
"current"/active memory concept anywhere in this API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from studybot.api.converters import learning_memory_to_out, memory_kind_info_to_out
from studybot.api.dependencies import require_token
from studybot.api.engine import Engine, get_engine
from studybot.api.errors import (
    CHAT_NOT_FOUND,
    COURSE_NOT_FOUND,
    INVALID_MEMORY_KIND,
    INVALID_MEMORY_STATUS,
    MEMORY_CONFLICT,
    MEMORY_NOT_FOUND,
    VALIDATION_ERROR,
    ApiError,
)
from studybot.api.schemas import LearningMemoryCreateIn, LearningMemoryOut, LearningMemoryUpdateIn, MemoryKindInfoOut
from studybot.core.exceptions import (
    ChatNotFoundError,
    CourseNotFoundError,
    MemoryConflictError,
    MemoryNotFoundError,
    SessionError,
)
from studybot.core.learning_memory import all_kinds, parse_memory_kind, parse_memory_status
from studybot.storage.base import UNSET

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/memory-kinds", response_model=list[MemoryKindInfoOut])
async def list_memory_kinds() -> list[MemoryKindInfoOut]:
    return [memory_kind_info_to_out(info) for info in all_kinds()]


@router.get("/memories", response_model=list[LearningMemoryOut])
async def list_memories(
    course_id: str | None = Query(default=None, description="Filter by course id, or 'none' for global-only"),
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    engine: Engine = Depends(get_engine),
) -> list[LearningMemoryOut]:
    if course_id is None:
        course_filter = UNSET
    elif course_id.lower() == "none":
        course_filter = None
    else:
        course_filter = course_id

    kind_filter = None
    if kind is not None:
        try:
            kind_filter = parse_memory_kind(kind)
        except ValueError as exc:
            raise ApiError(422, INVALID_MEMORY_KIND, f"Unknown learning memory kind: {kind!r}") from exc

    status_filter = None
    if status is not None:
        try:
            status_filter = parse_memory_status(status)
        except ValueError as exc:
            raise ApiError(422, INVALID_MEMORY_STATUS, f"Unknown learning memory status: {status!r}") from exc

    memories = await engine.call(
        engine.app.memories.list, course_id=course_filter, kind=kind_filter, status=status_filter
    )
    return [learning_memory_to_out(m) for m in memories]


@router.post("/memories", response_model=LearningMemoryOut, status_code=201)
async def create_memory(body: LearningMemoryCreateIn, engine: Engine = Depends(get_engine)) -> LearningMemoryOut:
    try:
        kind = parse_memory_kind(body.kind)
    except ValueError as exc:
        raise ApiError(422, INVALID_MEMORY_KIND, f"Unknown learning memory kind: {body.kind!r}") from exc

    try:
        memory = await engine.call(
            engine.app.memories.create,
            topic=body.topic,
            kind=kind,
            summary=body.summary,
            course_id=body.course_id,
            source_chat_id=body.source_chat_id,
        )
    except CourseNotFoundError as exc:
        raise ApiError(404, COURSE_NOT_FOUND, str(exc)) from exc
    except ChatNotFoundError as exc:
        raise ApiError(404, CHAT_NOT_FOUND, str(exc)) from exc
    except MemoryConflictError as exc:
        raise ApiError(409, MEMORY_CONFLICT, str(exc)) from exc
    except SessionError as exc:
        raise ApiError(422, VALIDATION_ERROR, str(exc)) from exc
    return learning_memory_to_out(memory)


@router.get("/memories/{memory_id}", response_model=LearningMemoryOut)
async def get_memory(memory_id: str, engine: Engine = Depends(get_engine)) -> LearningMemoryOut:
    try:
        memory = await engine.call(engine.app.memories.get, memory_id)
    except MemoryNotFoundError as exc:
        raise ApiError(404, MEMORY_NOT_FOUND, str(exc)) from exc
    return learning_memory_to_out(memory)


@router.patch("/memories/{memory_id}", response_model=LearningMemoryOut)
async def update_memory(
    memory_id: str, body: LearningMemoryUpdateIn, engine: Engine = Depends(get_engine)
) -> LearningMemoryOut:
    kind = None
    if body.kind is not None:
        try:
            kind = parse_memory_kind(body.kind)
        except ValueError as exc:
            raise ApiError(422, INVALID_MEMORY_KIND, f"Unknown learning memory kind: {body.kind!r}") from exc

    # `course_id` uses "was it present in the request at all" (not "is it
    # None") so that an explicit `courseId: null` (unassign) is
    # distinguishable from an omitted `courseId` (leave unchanged) — see
    # `LearningMemoryUpdateIn`'s docstring.
    course_id = body.course_id if "course_id" in body.model_fields_set else UNSET

    try:
        memory = await engine.call(
            engine.app.memories.update,
            memory_id,
            course_id=course_id,
            topic=body.topic,
            kind=kind,
            summary=body.summary,
        )
    except MemoryNotFoundError as exc:
        raise ApiError(404, MEMORY_NOT_FOUND, str(exc)) from exc
    except CourseNotFoundError as exc:
        raise ApiError(404, COURSE_NOT_FOUND, str(exc)) from exc
    except MemoryConflictError as exc:
        raise ApiError(409, MEMORY_CONFLICT, str(exc)) from exc
    except SessionError as exc:
        raise ApiError(422, VALIDATION_ERROR, str(exc)) from exc
    return learning_memory_to_out(memory)


@router.post("/memories/{memory_id}/archive", response_model=LearningMemoryOut)
async def archive_memory(memory_id: str, engine: Engine = Depends(get_engine)) -> LearningMemoryOut:
    try:
        memory = await engine.call(engine.app.memories.archive, memory_id)
    except MemoryNotFoundError as exc:
        raise ApiError(404, MEMORY_NOT_FOUND, str(exc)) from exc
    return learning_memory_to_out(memory)


@router.post("/memories/{memory_id}/restore", response_model=LearningMemoryOut)
async def restore_memory(memory_id: str, engine: Engine = Depends(get_engine)) -> LearningMemoryOut:
    try:
        memory = await engine.call(engine.app.memories.restore, memory_id)
    except MemoryNotFoundError as exc:
        raise ApiError(404, MEMORY_NOT_FOUND, str(exc)) from exc
    except MemoryConflictError as exc:
        raise ApiError(409, MEMORY_CONFLICT, str(exc)) from exc
    return learning_memory_to_out(memory)


@router.delete("/memories/{memory_id}", status_code=204, response_model=None)
async def delete_memory(memory_id: str, engine: Engine = Depends(get_engine)) -> None:
    try:
        await engine.call(engine.app.memories.delete, memory_id)
    except MemoryNotFoundError as exc:
        raise ApiError(404, MEMORY_NOT_FOUND, str(exc)) from exc
