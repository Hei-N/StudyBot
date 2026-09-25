"""Course business logic: validation and CRUD orchestration on top of
`CourseRepository`.

Keeps validation rules out of the CLI (which only does I/O and formatting)
and out of the repository (which stays a dumb data layer, like
`ChatRepository`). Reads `ChatRepository` only for the read-only "how many
chats does this course have" figure shown by `/course info` — it never
writes to it; chat mutations belong to `SessionService`.
"""

from __future__ import annotations

import uuid

from studybot.core.exceptions import SessionError
from studybot.storage.base import ChatRepository, Course, CourseRepository, LearningMemoryRepository

_MAX_NAME_LENGTH = 200
_MAX_CODE_LENGTH = 50
_MAX_TERM_LENGTH = 50


class CourseService:
    """Create, look up, edit, and delete courses."""

    def __init__(
        self,
        course_repository: CourseRepository,
        chat_repository: ChatRepository,
        memory_repository: LearningMemoryRepository | None = None,
    ) -> None:
        self._courses = course_repository
        self._chats = chat_repository
        # Optional (Stage 6.1): `None` only in tests/call sites that don't
        # care about learning memory at all — `delete_course` simply skips
        # the archiving step below, matching pre-Stage-6.1 behavior (the
        # database's own `ON DELETE SET NULL` still runs regardless, since
        # that's enforced by the schema, not by this service).
        self._memories = memory_repository

    def create_course(
        self,
        name: str,
        code: str | None = None,
        term: str | None = None,
        description: str | None = None,
    ) -> Course:
        name = self._validate_name(name)
        code = self._normalize_short_field(code, _MAX_CODE_LENGTH)
        term = self._normalize_short_field(term, _MAX_TERM_LENGTH)
        description = self._normalize_description(description)
        return self._courses.create_course(str(uuid.uuid4()), name, code, term, description)

    def get_course(self, course_id: str) -> Course | None:
        return self._courses.get_course(course_id)

    def list_courses(self) -> list[Course]:
        return self._courses.list_courses()

    def resolve_course(self, id_or_prefix: str) -> Course:
        """Find a course by exact id or unambiguous id prefix.

        Raises `SessionError` if nothing matches, or if more than one
        course matches — an ambiguous prefix must never silently pick one.
        """
        courses = self._courses.list_courses()

        exact = next((c for c in courses if c.id == id_or_prefix), None)
        if exact is not None:
            return exact

        matches = [c for c in courses if c.id.startswith(id_or_prefix)]
        if not matches:
            raise SessionError(f"No course found matching '{id_or_prefix}'.")
        if len(matches) > 1:
            raise SessionError(f"'{id_or_prefix}' matches {len(matches)} courses; use a longer id.")
        return matches[0]

    def edit_course(
        self,
        course_id: str,
        name: str,
        code: str | None,
        term: str | None,
        description: str | None,
    ) -> Course:
        name = self._validate_name(name)
        code = self._normalize_short_field(code, _MAX_CODE_LENGTH)
        term = self._normalize_short_field(term, _MAX_TERM_LENGTH)
        description = self._normalize_description(description)
        return self._courses.update_course(course_id, name, code, term, description)

    def delete_course(self, course_id: str) -> Course:
        """Delete a course. Its chats and their messages are untouched —
        `SQLiteCourseRepository` relies on ON DELETE SET NULL for that.

        Learning memory (Stage 6.1): the database's `ON DELETE SET NULL`
        on `learning_memories.course_id` would, by itself, turn every
        *active* memory that belonged to this course into an active
        *global* memory the instant the course disappears — silently
        injecting that subject's context into every other course's chats.
        To prevent that, every currently active memory in this course is
        archived *first* (a separate, ordinary repository call — the two
        calls are not one SQL transaction, but since every call into this
        service already runs on the API's single dedicated engine thread,
        or the CLI's single thread, no reader can ever observe the course
        gone while an affected memory is still active; a crash between the
        two calls leaves memories archived and the course still present,
        which is safe to retry). Only memories with `course_id ==
        course_id` are touched — memories that were already global, or
        belong to a different course, are never affected.

        The memory itself is never deleted, and never loses its content:
        after this call it is an archived, unassigned (course_id is now
        `None`, via the same `ON DELETE SET NULL`) memory, fully visible
        and editable via the usual `LearningMemoryService` operations. A
        user who wants it back has two explicit choices — `restore()` it
        (making it an active *global* memory, since its course is gone),
        or `update()` its `course_id` to a different existing course first
        (then optionally restore it into that course instead). Neither
        happens automatically; both require the same deliberate action a
        brand-new global/reassigned memory would.
        """
        course = self._courses.get_course(course_id)
        if course is None:
            raise SessionError(f"No course found matching '{course_id}'.")
        if self._memories is not None:
            self._memories.archive_for_course(course_id)
        self._courses.delete_course(course_id)
        return course

    def count_chats(self, course_id: str) -> int:
        return self._chats.count_chats_for_course(course_id)

    @staticmethod
    def _validate_name(name: str) -> str:
        normalized = " ".join(name.split())
        if not normalized:
            raise SessionError("A course name cannot be empty.")
        if len(normalized) > _MAX_NAME_LENGTH:
            raise SessionError(f"Course name is too long (max {_MAX_NAME_LENGTH} characters).")
        return normalized

    @staticmethod
    def _normalize_short_field(value: str | None, max_length: int) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized[:max_length] or None

    @staticmethod
    def _normalize_description(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
