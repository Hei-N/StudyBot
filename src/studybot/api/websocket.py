"""WebSocket streaming chat — the primary way a client sends a message and
receives a response.

Reuses `SessionService.send_streaming_to_chat()` (Stage 5.8's explicit-by-id
layer) — there is no second streaming implementation, and no "activate this
chat first" step: each `send_message` loads exactly the chat it names,
fresh from the repository, regardless of what other chats have been
created or messaged on this or any other connection in the meantime. See
`core/session_service.py`'s module docstring for the full rationale, and
API_CONTRACT.md for the event protocol and documented client-disconnect
behavior.

`SessionService.send_streaming_to_chat` is a plain (synchronous) generator
— each `next()` call is dispatched to the same dedicated engine thread
every other API call uses (see `api/engine.py`), both so a slow/blocking
Ollama call never stalls the event loop for other connections, and so it
never touches the shared SQLite connection from the wrong thread.
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
    """Adapt a synchronous generator to an async one, running each `next()`
    call on the engine's dedicated thread. Exceptions raised inside the
    generator (e.g. `ModelError`, `ChatBusyError`) propagate through
    normally — including on the very first `next()`, since
    `send_streaming_to_chat` resolves the chat id and acquires its
    generation lock lazily, not at generator-construction time."""
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
        # Reject before accept(): no data is exchanged with an unauthenticated
        # client at all.
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

    # Checked explicitly (and stateless-ly — no cursor touched) before
    # `message_started` is sent, so an unknown chat id fails fast with just
    # an `error` event, exactly like the old cursor-based `_activate()`
    # pre-check did — `send_streaming_to_chat` would also raise
    # `ChatNotFoundError`, but only lazily on the first `next()`, which
    # would otherwise leave a stray `message_started` for a chat that was
    # never going to work.
    if await engine.call(engine.app.sessions.get_chat, chat_id) is None:
        await _send_error(websocket, CHAT_NOT_FOUND, f"No chat found with id '{chat_id}'.", chat_id)
        return

    await websocket.send_json({"type": "message_started", "chatId": chat_id})

    generator = await engine.call(engine.app.sessions.send_streaming_to_chat, chat_id, content)
    try:
        async for chunk in _iterate_in_thread(engine, generator):
            await websocket.send_json({"type": "delta", "content": chunk, "chatId": chat_id})
    except ChatNotFoundError as exc:
        await _send_error(websocket, CHAT_NOT_FOUND, str(exc), chat_id)
        return
    except ChatBusyError as exc:
        await _send_error(websocket, CHAT_BUSY, str(exc), chat_id)
        return
    except ModelError as exc:
        # A failed generation persists only the user's message (the same
        # guarantee ChatService/SessionService have had since Stage 2) — no
        # incomplete assistant reply is ever sent as if it were complete.
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
