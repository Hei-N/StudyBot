"""Chat endpoints — thin translation onto the existing `SessionService`.

Architectural note (active-session limitation, documented rather than
"fixed" — see API_CONTRACT.md): `SessionService` was designed around one
mutable "active chat" cursor per process (see its module docstring). Reads
that don't need a live `ChatService` (list/get/history) use the stateless
`get_chat`/`get_chat_history_records` passthroughs added for this API and
never touch that cursor. Writes that inherently operate through the active
chat (rename/clear/delete/move/mode) switch the cursor to the requested
`chat_id` first via `_activate()` below — safe and correct for the single
engine-process-per-app-instance model this stage targets, but requests
targeting *different* chat ids are not safe to interleave concurrently
against one running server process. Every call to `SessionService`/
`CourseService` is dispatched via `Engine.call` — see `api/engine.py` for
why (SQLite connection thread-affinity).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from studybot.api.converters import chat_to_out, message_record_to_out, mode_info_to_out
from studybot.api.dependencies import require_token
from studybot.api.engine import Engine, get_engine
from studybot.api.errors import CHAT_NOT_FOUND, COURSE_NOT_FOUND, INVALID_MODE, VALIDATION_ERROR, ApiError
from studybot.api.schemas import (
    ChatCourseIn,
    ChatCreateIn,
    ChatModeIn,
    ChatOut,
    ChatRenameIn,
    MessageOut,
    ModeInfoOut,
)
from studybot.core.exceptions import SessionError
from studybot.core.teaching_mode import get_mode_info, parse_teaching_mode

router = APIRouter(dependencies=[Depends(require_token)])


async def _activate(engine: Engine, chat_id: str) -> None:
    """Make `chat_id` the process's active chat if it isn't already.

    Chat ids are full stable UUIDs (never CLI-style short prefixes) here,
    so this always resolves exactly or not at all — see the module
    docstring for the concurrency caveat this implies.
    """
    active = await engine.call(lambda: engine.app.sessions.active_session)
    if active.id == chat_id:
        return
    try:
        await engine.call(engine.app.sessions.open_chat, chat_id)
    except SessionError as exc:
        raise ApiError(404, CHAT_NOT_FOUND, f"No chat found with id '{chat_id}'.") from exc


@router.get("/chats", response_model=list[ChatOut])
async def list_chats(
    course_id: str | None = Query(default=None, description="Filter by course id, or 'none' for General"),
    engine: Engine = Depends(get_engine),
) -> list[ChatOut]:
    if course_id is None:
        chats = await engine.call(engine.app.sessions.list_chats)
    elif course_id.lower() == "none":
        chats = await engine.call(engine.app.sessions.list_chats_in_course, None)
    else:
        chats = await engine.call(engine.app.sessions.list_chats_in_course, course_id)
    return [chat_to_out(c) for c in chats]


@router.post("/chats", response_model=ChatOut, status_code=201)
async def create_chat(body: ChatCreateIn, engine: Engine = Depends(get_engine)) -> ChatOut:
    if body.course_id is not None:
        course = await engine.call(engine.app.courses.get_course, body.course_id)
        if course is None:
            raise ApiError(404, COURSE_NOT_FOUND, f"No course found with id '{body.course_id}'.")
    # Explicit, not the CLI's "inherit whatever's currently active" default
    # — a stateless API call always gets exactly the course it asked for.
    chat = await engine.call(engine.app.sessions.new_chat, body.course_id)
    return chat_to_out(chat)


@router.get("/chats/{chat_id}", response_model=ChatOut)
async def get_chat(chat_id: str, engine: Engine = Depends(get_engine)) -> ChatOut:
    chat = await engine.call(engine.app.sessions.get_chat, chat_id)
    if chat is None:
        raise ApiError(404, CHAT_NOT_FOUND, f"No chat found with id '{chat_id}'.")
    return chat_to_out(chat)


@router.get("/chats/{chat_id}/messages", response_model=list[MessageOut])
async def get_chat_messages(chat_id: str, engine: Engine = Depends(get_engine)) -> list[MessageOut]:
    if await engine.call(engine.app.sessions.get_chat, chat_id) is None:
        raise ApiError(404, CHAT_NOT_FOUND, f"No chat found with id '{chat_id}'.")
    records = await engine.call(engine.app.sessions.get_chat_history_records, chat_id)
    return [message_record_to_out(r) for r in records]


@router.put("/chats/{chat_id}/rename", response_model=ChatOut)
async def rename_chat(chat_id: str, body: ChatRenameIn, engine: Engine = Depends(get_engine)) -> ChatOut:
    await _activate(engine, chat_id)
    try:
        chat = await engine.call(engine.app.sessions.rename_active_chat, body.title)
    except SessionError as exc:
        raise ApiError(422, VALIDATION_ERROR, str(exc)) from exc
    return chat_to_out(chat)


@router.post("/chats/{chat_id}/clear", response_model=ChatOut)
async def clear_chat(chat_id: str, engine: Engine = Depends(get_engine)) -> ChatOut:
    await _activate(engine, chat_id)
    await engine.call(engine.app.sessions.clear_active_chat)
    chat = await engine.call(lambda: engine.app.sessions.active_session)
    return chat_to_out(chat)


@router.delete("/chats/{chat_id}", status_code=204, response_model=None)
async def delete_chat(chat_id: str, engine: Engine = Depends(get_engine)) -> None:
    await _activate(engine, chat_id)
    await engine.call(engine.app.sessions.delete_active_chat)


@router.put("/chats/{chat_id}/course", response_model=ChatOut)
async def assign_chat_course(
    chat_id: str, body: ChatCourseIn, engine: Engine = Depends(get_engine)
) -> ChatOut:
    await _activate(engine, chat_id)
    try:
        chat = await engine.call(engine.app.sessions.move_active_chat_to_course, body.course_id)
    except SessionError as exc:
        raise ApiError(404, COURSE_NOT_FOUND, str(exc)) from exc
    return chat_to_out(chat)


@router.get("/chats/{chat_id}/mode", response_model=ModeInfoOut)
async def get_chat_mode(chat_id: str, engine: Engine = Depends(get_engine)) -> ModeInfoOut:
    await _activate(engine, chat_id)
    mode = await engine.call(engine.app.sessions.get_teaching_mode)
    return mode_info_to_out(get_mode_info(mode))


@router.put("/chats/{chat_id}/mode", response_model=ModeInfoOut)
async def set_chat_mode(chat_id: str, body: ChatModeIn, engine: Engine = Depends(get_engine)) -> ModeInfoOut:
    await _activate(engine, chat_id)
    try:
        mode = parse_teaching_mode(body.mode)
    except ValueError as exc:
        raise ApiError(422, INVALID_MODE, f"Unknown teaching mode: {body.mode!r}") from exc
    await engine.call(engine.app.sessions.set_teaching_mode, mode)
    return mode_info_to_out(get_mode_info(mode))
