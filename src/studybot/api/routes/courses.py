"""Course endpoints — thin translation onto the existing `CourseService`.

No course business logic (validation, delete semantics) lives here; it's
all in `core.course_service.CourseService`, exactly as the CLI uses it.
Every call to it is dispatched via `Engine.call` — see `api/engine.py` for
why that's necessary (SQLite connection thread-affinity).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from studybot.api.converters import course_to_out
from studybot.api.dependencies import require_token
from studybot.api.engine import Engine, get_engine
from studybot.api.errors import COURSE_NOT_FOUND, VALIDATION_ERROR, ApiError
from studybot.api.schemas import CourseCreateIn, CourseOut, CourseUpdateIn
from studybot.core.exceptions import SessionError

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/courses", response_model=list[CourseOut])
async def list_courses(engine: Engine = Depends(get_engine)) -> list[CourseOut]:
    courses = await engine.call(engine.app.courses.list_courses)
    return [course_to_out(c) for c in courses]


@router.post("/courses", response_model=CourseOut, status_code=201)
async def create_course(body: CourseCreateIn, engine: Engine = Depends(get_engine)) -> CourseOut:
    try:
        course = await engine.call(
            engine.app.courses.create_course, body.name, body.code, body.term, body.description
        )
    except SessionError as exc:
        raise ApiError(422, VALIDATION_ERROR, str(exc)) from exc
    return course_to_out(course)


@router.get("/courses/{course_id}", response_model=CourseOut)
async def get_course(course_id: str, engine: Engine = Depends(get_engine)) -> CourseOut:
    course = await engine.call(engine.app.courses.get_course, course_id)
    if course is None:
        raise ApiError(404, COURSE_NOT_FOUND, f"No course found with id '{course_id}'.")
    return course_to_out(course)


@router.put("/courses/{course_id}", response_model=CourseOut)
async def update_course(
    course_id: str, body: CourseUpdateIn, engine: Engine = Depends(get_engine)
) -> CourseOut:
    if await engine.call(engine.app.courses.get_course, course_id) is None:
        raise ApiError(404, COURSE_NOT_FOUND, f"No course found with id '{course_id}'.")
    try:
        course = await engine.call(
            engine.app.courses.edit_course, course_id, body.name, body.code, body.term, body.description
        )
    except SessionError as exc:
        raise ApiError(422, VALIDATION_ERROR, str(exc)) from exc
    return course_to_out(course)


@router.delete("/courses/{course_id}", status_code=204, response_model=None)
async def delete_course(course_id: str, engine: Engine = Depends(get_engine)) -> None:
    try:
        await engine.call(engine.app.courses.delete_course, course_id)
    except SessionError as exc:
        raise ApiError(404, COURSE_NOT_FOUND, str(exc)) from exc
    # Chats/messages are untouched by design (ON DELETE SET NULL) — this
    # only refreshes this process's in-memory active-chat context in case
    # it was showing the now-deleted course, mirroring the CLI's own
    # `/course delete` handling. A no-op if unrelated to the active chat.
    await engine.call(engine.app.sessions.sync_active_chat_course)
