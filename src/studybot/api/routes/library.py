"""Study library endpoints: sources and their opaque authorization.

Thin translation onto ``LibraryService``. The authorization payload is Base64 on
the wire and never appears in source listings, logs or error messages.
"""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, Response

from studybot.api.converters import authorization_to_out, library_source_to_out
from studybot.api.dependencies import require_token
from studybot.api.engine import Engine, get_engine
from studybot.api.errors import (
    LIBRARY_AUTHORIZATION_NOT_FOUND,
    LIBRARY_SOURCE_NOT_FOUND,
    VALIDATION_ERROR,
    ApiError,
)
from studybot.api.schemas import AuthorizationIn, AuthorizationOut, LibrarySourceOut, LocalFolderSourceIn
from studybot.core.exceptions import (
    LibraryAuthorizationNotFoundError,
    LibrarySourceNotFoundError,
    SessionError,
)
from studybot.core.library import MAX_AUTHORIZATION_BYTES

router = APIRouter(prefix="/library", dependencies=[Depends(require_token)])

_MAX_ENCODED_LENGTH = (MAX_AUTHORIZATION_BYTES // 3 + 1) * 4


def _decode_payload(encoded: str) -> bytes:
    if len(encoded) > _MAX_ENCODED_LENGTH:
        raise ApiError(422, VALIDATION_ERROR, "The authorization data is too large.")
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(422, VALIDATION_ERROR, "The authorization data is not valid Base64.") from None


def _translate(exc: SessionError) -> ApiError:
    if isinstance(exc, LibrarySourceNotFoundError):
        return ApiError(404, LIBRARY_SOURCE_NOT_FOUND, str(exc))
    if isinstance(exc, LibraryAuthorizationNotFoundError):
        return ApiError(404, LIBRARY_AUTHORIZATION_NOT_FOUND, str(exc))
    return ApiError(422, VALIDATION_ERROR, str(exc))


@router.get("/sources", response_model=list[LibrarySourceOut])
async def list_sources(engine: Engine = Depends(get_engine)) -> list[LibrarySourceOut]:
    library = engine.app.library
    sources = await engine.call(library.list_sources)
    authorized = await engine.call(library.authorized_source_ids)
    return [library_source_to_out(s, s.id in authorized) for s in sources]


@router.post("/sources/local-folder", response_model=LibrarySourceOut, status_code=201)
async def authorize_local_folder(
    body: LocalFolderSourceIn, response: Response, engine: Engine = Depends(get_engine)
) -> LibrarySourceOut:
    """Create the source, or refresh the authorization of an already-known folder (HTTP 200)."""
    payload = _decode_payload(body.authorization.payload)
    try:
        source, created = await engine.call(
            engine.app.library.authorize_local_folder,
            body.display_name,
            body.locator,
            body.authorization.platform,
            body.authorization.kind,
            payload,
        )
    except SessionError as exc:
        raise _translate(exc) from exc
    if not created:
        response.status_code = 200
    return library_source_to_out(source, True)


@router.delete("/sources/{source_id}", status_code=204, response_model=None)
async def delete_source(source_id: str, engine: Engine = Depends(get_engine)) -> None:
    """Remove the source and its stored authorization. Real files are never touched."""
    try:
        await engine.call(engine.app.library.delete_source, source_id)
    except SessionError as exc:
        raise _translate(exc) from exc


@router.get("/sources/{source_id}/authorization", response_model=AuthorizationOut)
async def get_authorization(source_id: str, engine: Engine = Depends(get_engine)) -> AuthorizationOut:
    try:
        authorization = await engine.call(engine.app.library.get_authorization, source_id)
    except SessionError as exc:
        raise _translate(exc) from exc
    return authorization_to_out(authorization)


@router.put("/sources/{source_id}/authorization", response_model=LibrarySourceOut)
async def replace_authorization(
    source_id: str, body: AuthorizationIn, engine: Engine = Depends(get_engine)
) -> LibrarySourceOut:
    payload = _decode_payload(body.payload)
    try:
        source = await engine.call(
            engine.app.library.set_authorization, source_id, body.platform, body.kind, payload
        )
    except SessionError as exc:
        raise _translate(exc) from exc
    return library_source_to_out(source, True)
