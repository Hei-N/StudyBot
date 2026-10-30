"""Chat endpoints: thin translation onto ``SessionService``'s explicit-by-id operations.

Every route addresses its chat by the ``chat_id`` in the URL and never uses the
CLI's active-chat cursor. Calls are dispatched via ``Engine.call`` (see
``api/engine.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from studybot.api.converters import chat_to_out, message_record_to_out, mode_info_to_out, reasoning_mode_info_to_out
from studybot.api.dependencies import require_token
from studybot.api.engine import Engine, get_engine
from studybot.api.errors import (
    CHAT_NOT_FOUND,
    COURSE_NOT_FOUND,
    INVALID_MODE,
    INVALID_REASONING_MODE,
    VALIDATION_ERROR,
    ApiError,
)
from studybot.api.schemas import (
    ChatCourseIn,
    ChatCreateIn,
    ChatModeIn,
    ChatOut,
    ChatReasoningModeIn,
    ChatRenameIn,
    MessageOut,
    ModeInfoOut,
)
from studybot.core.exceptions import ChatNotFoundError, SessionError
from studybot.core.reasoning_mode import get_mode_info as get_reasoning_mode_info
from studybot.core.reasoning_mode import parse_reasoning_mode
from studybot.core.teaching_mode import get_mode_info, parse_teaching_mode

router = APIRouter(dependencies=[Depends(require_token)])


async def _release_files(request: Request, engine: Engine, file_ids: list[str]) -> None:
    """Chat-only uploads that lost their last message are removed; kept library files are not."""
    if not file_ids:
        return
    for stored_name in await engine.call(engine.app.library.release_chat_files, file_ids):
        request.app.state.uploads.discard(stored_name)


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
    # Persisted immediately: the returned id is addressable even with zero messages.
    chat = await engine.call(engine.app.sessions.create_chat, body.course_id)
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
    try:
        chat = await engine.call(engine.app.sessions.rename_chat, chat_id, body.title)
    except ChatNotFoundError as exc:
        raise ApiError(404, CHAT_NOT_FOUND, str(exc)) from exc
    except SessionError as exc:
        raise ApiError(422, VALIDATION_ERROR, str(exc)) from exc
    return chat_to_out(chat)


@router.post("/chats/{chat_id}/clear", response_model=ChatOut)
async def clear_chat(chat_id: str, request: Request, engine: Engine = Depends(get_engine)) -> ChatOut:
    attached = await engine.call(engine.app.sessions.attachment_file_ids, chat_id)
    try:
        chat = await engine.call(engine.app.sessions.clear_chat, chat_id)
    except ChatNotFoundError as exc:
        raise ApiError(404, CHAT_NOT_FOUND, str(exc)) from exc
    await _release_files(request, engine, attached)
    return chat_to_out(chat)


@router.delete("/chats/{chat_id}", status_code=204, response_model=None)
async def delete_chat(chat_id: str, request: Request, engine: Engine = Depends(get_engine)) -> None:
    attached = await engine.call(engine.app.sessions.attachment_file_ids, chat_id)
    try:
        await engine.call(engine.app.sessions.delete_chat, chat_id)
    except ChatNotFoundError as exc:
        raise ApiError(404, CHAT_NOT_FOUND, str(exc)) from exc
    await _release_files(request, engine, attached)


@router.put("/chats/{chat_id}/course", response_model=ChatOut)
async def assign_chat_course(
    chat_id: str, body: ChatCourseIn, engine: Engine = Depends(get_engine)
) -> ChatOut:
    try:
        chat = await engine.call(engine.app.sessions.assign_course_to_chat, chat_id, body.course_id)
    except ChatNotFoundError as exc:
        raise ApiError(404, CHAT_NOT_FOUND, str(exc)) from exc
    except SessionError as exc:
        raise ApiError(404, COURSE_NOT_FOUND, str(exc)) from exc
    return chat_to_out(chat)


@router.get("/chats/{chat_id}/mode", response_model=ModeInfoOut)
async def get_chat_mode(chat_id: str, engine: Engine = Depends(get_engine)) -> ModeInfoOut:
    chat = await engine.call(engine.app.sessions.get_chat, chat_id)
    if chat is None:
        raise ApiError(404, CHAT_NOT_FOUND, f"No chat found with id '{chat_id}'.")
    return mode_info_to_out(get_mode_info(chat.teaching_mode))


@router.put("/chats/{chat_id}/mode", response_model=ModeInfoOut)
async def set_chat_mode(chat_id: str, body: ChatModeIn, engine: Engine = Depends(get_engine)) -> ModeInfoOut:
    try:
        mode = parse_teaching_mode(body.mode)
    except ValueError as exc:
        raise ApiError(422, INVALID_MODE, f"Unknown teaching mode: {body.mode!r}") from exc
    try:
        await engine.call(engine.app.sessions.set_teaching_mode_for_chat, chat_id, mode)
    except ChatNotFoundError as exc:
        raise ApiError(404, CHAT_NOT_FOUND, str(exc)) from exc
    return mode_info_to_out(get_mode_info(mode))


@router.get("/chats/{chat_id}/reasoning-mode", response_model=ModeInfoOut)
async def get_chat_reasoning_mode(chat_id: str, engine: Engine = Depends(get_engine)) -> ModeInfoOut:
    chat = await engine.call(engine.app.sessions.get_chat, chat_id)
    if chat is None:
        raise ApiError(404, CHAT_NOT_FOUND, f"No chat found with id '{chat_id}'.")
    return reasoning_mode_info_to_out(get_reasoning_mode_info(chat.reasoning_mode))


@router.put("/chats/{chat_id}/reasoning-mode", response_model=ModeInfoOut)
async def set_chat_reasoning_mode(
    chat_id: str, body: ChatReasoningModeIn, engine: Engine = Depends(get_engine)
) -> ModeInfoOut:
    try:
        mode = parse_reasoning_mode(body.reasoning_mode)
    except ValueError as exc:
        raise ApiError(422, INVALID_REASONING_MODE, f"Unknown reasoning mode: {body.reasoning_mode!r}") from exc
    try:
        await engine.call(engine.app.sessions.set_reasoning_mode_for_chat, chat_id, mode)
    except ChatNotFoundError as exc:
        raise ApiError(404, CHAT_NOT_FOUND, str(exc)) from exc
    return reasoning_mode_info_to_out(get_reasoning_mode_info(mode))
