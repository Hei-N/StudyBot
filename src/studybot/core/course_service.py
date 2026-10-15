"""Course validation and CRUD on top of ``CourseRepository``.

Reads ``ChatRepository`` only for the chat count shown by ``/course info``;
chat mutations belong to ``SessionService``.
"""

from __future__ import annotations

import uuid

from studybot.core.exceptions import SessionError
from studybot.storage.base import ChatRepository, Course, CourseRepository

_MAX_NAME_LENGTH = 200
_MAX_CODE_LENGTH = 50
_MAX_TERM_LENGTH = 50


class CourseService:
    """Create, look up, edit and delete courses."""

    def __init__(self, course_repository: CourseRepository, chat_repository: ChatRepository) -> None:
        self._courses = course_repository
        self._chats = chat_repository

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
        """Find a course by exact id or unambiguous prefix.

        Raises ``SessionError`` if nothing matches or more than one course does.
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
        """Delete a course; its chats and messages are kept.

        The course's active learning memories are archived in the same transaction
        (``CourseRepository.delete_course_archiving_memories``). Otherwise
        ``ON DELETE SET NULL`` would turn them into active global memories. Archived
        memories keep their content and can be restored (as global) or reassigned to
        another course.
        """
        course = self._courses.get_course(course_id)
        if course is None:
            raise SessionError(f"No course found matching '{course_id}'.")
        self._courses.delete_course_archiving_memories(course_id)
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
