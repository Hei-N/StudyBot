"""Transport DTOs for the API.

These define the wire contract the Flutter client depends on and are kept
separate from the domain types; ``api/converters.py`` converts between them.
Fields are emitted as camelCase via ``ApiModel``'s alias generator, while
Python code uses snake_case.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# --- health ------------------------------------------------------------------------


class HealthOut(ApiModel):
    api_version: str
    status: str
    provider: str
    model: str
    provider_reachable: bool | None
    model_available: bool | None


# --- courses -----------------------------------------------------------------------


class CourseOut(ApiModel):
    id: str
    name: str
    code: str | None
    term: str | None
    description: str | None
    created_at: str
    updated_at: str


class CourseCreateIn(ApiModel):
    name: str
    code: str | None = None
    term: str | None = None
    description: str | None = None


class CourseUpdateIn(ApiModel):
    """Full replace, matching ``CourseService.edit_course``: send unchanged fields
    back as-is. There is no null-means-keep merge.
    """

    name: str
    code: str | None = None
    term: str | None = None
    description: str | None = None


# --- teaching modes ------------------------------------------------------------------


class ModeInfoOut(ApiModel):
    """Shared shape for the teaching-mode and reasoning-mode catalogs: a stable id plus display metadata.
    """

    id: str
    display_name: str
    description: str


class ChatModeIn(ApiModel):
    mode: str


# --- reasoning modes -----------------------------------------------------------------


class ChatReasoningModeIn(ApiModel):
    reasoning_mode: str


# --- chats ---------------------------------------------------------------------------


class ChatOut(ApiModel):
    id: str
    title: str | None
    course_id: str | None
    teaching_mode: str
    reasoning_mode: str
    created_at: str
    updated_at: str


class ChatCreateIn(ApiModel):
    course_id: str | None = None


class ChatRenameIn(ApiModel):
    title: str


class ChatCourseIn(ApiModel):
    course_id: str | None = None


class MessageOut(ApiModel):
    id: int
    role: str
    content: str
    created_at: str


# --- learning memory --------------------------------------------------------------


class MemoryKindInfoOut(ApiModel):
    """Catalog entry for ``GET /memory-kinds``: a stable id plus display metadata."""

    id: str
    display_name: str
    description: str


class LearningMemoryOut(ApiModel):
    id: str
    course_id: str | None
    source_chat_id: str | None
    topic: str
    kind: str
    summary: str
    status: str
    created_at: str
    updated_at: str


class LearningMemoryCreateIn(ApiModel):
    topic: str
    kind: str
    summary: str
    course_id: str | None = None
    source_chat_id: str | None = None


class LearningMemoryUpdateIn(ApiModel):
    """PATCH semantics: an omitted field is left unchanged.

    For ``topic``, ``kind`` and ``summary`` an explicit null is treated as omitted.
    ``course_id`` differs: an explicit null means "unassign to General", which is
    distinct from omitting it. The route tells the two apart with Pydantic's
    ``model_fields_set``.
    """

    topic: str | None = None
    kind: str | None = None
    summary: str | None = None
    course_id: str | None = None


# --- study library -----------------------------------------------------------------


class LibrarySourceOut(ApiModel):
    """A library source. ``locator`` is private local data; the authorization payload
    is never part of this DTO."""

    id: str
    course_id: str | None
    kind: str
    display_name: str
    locator: str
    created_at: str
    updated_at: str
    has_authorization: bool


class AuthorizationIn(ApiModel):
    platform: str
    kind: str
    payload: str  # Base64 of the opaque authorization bytes


class AuthorizationOut(ApiModel):
    source_id: str
    platform: str
    kind: str
    payload: str


class LocalFolderSourceIn(ApiModel):
    display_name: str
    locator: str
    authorization: AuthorizationIn


class LibraryFileOut(ApiModel):
    """A library file's metadata and processing state. Never contains page text or paths."""

    id: str
    source_id: str
    relative_path: str
    display_name: str
    extension: str | None
    size_bytes: int | None
    processing_state: str
    failure_code: str | None
    page_count: int | None
    text_page_count: int | None
    processing_version: str | None
    indexed_at: str | None
    updated_at: str


class ImportPdfIn(ApiModel):
    staging_id: str
    relative_path: str
    display_name: str | None = None


class ImportPdfOut(ApiModel):
    outcome: str  # "imported", "unchanged" or "failed"
    file: LibraryFileOut


class StagingDirectoryOut(ApiModel):
    path: str
