"""WebSocket streaming chat.

Reuses ``SessionService.send_streaming_to_chat``: each ``send_message`` loads
exactly the chat it names, so chats and connections do not affect each other.
See API_CONTRACT.md for the event protocol.

The service method is a synchronous generator. Each ``next()`` runs on the
shared engine thread (``api/engine.py``), so a slow model call never blocks
the event loop and the SQLite connection is only used from its own thread.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Iterator

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from studybot.api.auth import extract_bearer_token, token_matches
from studybot.api.converters import message_record_to_out
from studybot.api.engine import Engine
from studybot.api.errors import CHAT_BUSY, CHAT_NOT_FOUND, MODEL_ERROR, VALIDATION_ERROR
from studybot.core.exceptions import ChatBusyError, ChatNotFoundError, ModelError

logger = logging.getLogger(__name__)

router = APIRouter()

_UNAUTHORIZED_WS_CLOSE_CODE = 4401


async def _iterate_in_thread(engine: Engine, generator: Iterator[str]) -> AsyncIterator[str]:
    """Adapt a synchronous generator to an async one, running each ``next()`` on the
    engine thread.

    Errors from the generator (``ModelError``, ``ChatBusyError``) propagate,
    including from the first ``next()``, since the chat lookup and lock
    acquisition happen lazily.
    """
    sentinel = object()
    while True:
        chunk = await engine.call(next, generator, sentinel)
        if chunk is sentinel:
            return
        yield chunk


@router.websocket("/ws/chat")
async def chat_stream(websocket: WebSocket) -> None:
    engine: Engine = websocket.app.state.engine
    provided = extract_bearer_token(websocket.headers.get("authorization"))
    if not token_matches(provided, websocket.app.state.api_token):
        # Reject before accept(): exchange no data with unauthenticated clients.
        await websocket.close(code=_UNAUTHORIZED_WS_CLOSE_CODE)
        return

    await websocket.accept()
    try:
        while True:
            payload = await websocket.receive_json()
            await _handle_message(websocket, engine, payload)
    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")


async def _handle_message(websocket: WebSocket, engine: Engine, payload: Any) -> None:
    if not isinstance(payload, dict) or payload.get("type") != "send_message":
        await _send_error(websocket, VALIDATION_ERROR, "Expected {'type': 'send_message', ...}.")
        return

    chat_id = payload.get("chat_id")
    content = payload.get("content")
    if not isinstance(chat_id, str) or not chat_id or not isinstance(content, str) or not content.strip():
        await _send_error(
            websocket,
            VALIDATION_ERROR,
            "'chat_id' and non-empty 'content' are required.",
            chat_id if isinstance(chat_id, str) else None,
        )
        return

    # Check the chat first so an unknown id yields a single error event
    # instead of a stray message_started.
    if await engine.call(engine.app.sessions.get_chat, chat_id) is None:
        await _send_error(websocket, CHAT_NOT_FOUND, f"No chat found with id '{chat_id}'.", chat_id)
        return

    await websocket.send_json({"type": "message_started", "chatId": chat_id})

    generator = await engine.call(engine.app.sessions.send_streaming_to_chat, chat_id, content)
    try:
        async for chunk in _iterate_in_thread(engine, generator):
            if chunk:  # "" is a progress signal (see ModelProvider.stream): never sent
                await websocket.send_json({"type": "delta", "content": chunk, "chatId": chat_id})
    except ChatNotFoundError as exc:
        await _send_error(websocket, CHAT_NOT_FOUND, str(exc), chat_id)
        return
    except ChatBusyError as exc:
        await _send_error(websocket, CHAT_BUSY, str(exc), chat_id)
        return
    except ModelError as exc:
        # A failed generation persists only the user's message; an incomplete
        # reply is never sent as complete.
        await _send_error(websocket, MODEL_ERROR, str(exc), chat_id)
        return
    finally:
        await engine.call(generator.close)

    records = await engine.call(engine.app.sessions.get_chat_history_records, chat_id)
    last_message = records[-1] if records else None
    await websocket.send_json(
        {
            "type": "message_completed",
            "chatId": chat_id,
            "message": message_record_to_out(last_message).model_dump(by_alias=True)
            if last_message is not None
            else None,
        }
    )


async def _send_error(websocket: WebSocket, code: str, message: str, chat_id: str | None = None) -> None:
    payload: dict[str, Any] = {"type": "error", "code": code, "message": message}
    if chat_id is not None:
        payload["chatId"] = chat_id
    await websocket.send_json(payload)
