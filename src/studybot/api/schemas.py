"""Transport DTOs for the Study Bot API.

Deliberately separate from the domain dataclasses in `storage.base` /
`core.teaching_mode`: these are the wire contract Flutter depends on, and
must be free to evolve independently of internal representations (and vice
versa). Route handlers convert between the two in `api/converters.py` —
nothing here talks to a repository or a service.

Field names are emitted as camelCase (Flutter/Dart's own JSON convention)
via `ApiModel`'s alias generator, while Python code reads/writes plain
snake_case attributes.
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
    """Full replace, matching `CourseService.edit_course`'s existing
    contract exactly — send the fields you want kept unchanged back as-is.
    There is no null-means-keep merge logic here; that's CLI-only
    presentation behavior, not something the service supports, and the API
    does not duplicate it."""

    name: str
    code: str | None = None
    term: str | None = None
    description: str | None = None


# --- teaching modes ------------------------------------------------------------------


class ModeInfoOut(ApiModel):
    """Shared shape for both catalogs: teaching modes (`GET /modes`) and
    reasoning modes (`GET /reasoning-modes`) — both are just a stable id
    plus display metadata, so one DTO serves both rather than duplicating
    an identical schema under a second name."""

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


# --- learning memory (Stage 6) ---------------------------------------------------------


class MemoryKindInfoOut(ApiModel):
    """Catalog entry for `GET /memory-kinds` — a stable id plus
    natural-language display metadata, exactly like `ModeInfoOut`."""

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
    """PATCH semantics: every field is optional, and an *omitted* field
    means "leave unchanged". `topic`/`kind`/`summary` additionally treat an
    explicit `null` the same as omitted (a real value can never
    legitimately be null once validated, so there's no ambiguity to
    resolve). `course_id` is different: explicit `null` is a real,
    meaningful value ("unassign to General"), distinct from omitting it
    entirely ("leave unchanged") — the route handler distinguishes the two
    via Pydantic's `model_fields_set`, checking whether `course_id` was
    actually present in the request body at all, mirroring
    `storage.base.UNSET`'s purpose at the transport boundary."""

    topic: str | None = None
    kind: str | None = None
    summary: str | None = None
    course_id: str | None = None
