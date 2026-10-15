"""Learning-memory business logic.

Covers validation and normalization, the duplicate and supersession policy,
course-scoped CRUD, and the compact context block added to a chat's system
prompt. The repository stays a plain data layer, and nothing else (API,
Flutter, the model provider) knows what a learning memory is.

Memories are created only by explicit actions; this module never runs a model
or reads chat history.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from studybot.core.exceptions import (
    ChatNotFoundError,
    CourseNotFoundError,
    MemoryConflictError,
    MemoryNotFoundError,
    SessionError,
)
from studybot.core.learning_memory import (
    DEFAULT_MEMORY_STATUS,
    MemoryKind,
    MemoryStatus,
    get_kind_info,
    opposes,
)
from studybot.storage.base import UNSET, ChatRepository, CourseRepository, LearningMemory, LearningMemoryRepository

_MAX_TOPIC_LENGTH = 200
_MAX_SUMMARY_LENGTH = 4000

# Limits for the memory block in the system prompt: at most 12 entries and
# about 1200 characters, to keep it cheap on every request.
MAX_CONTEXT_ENTRIES = 12
MAX_CONTEXT_CHARS = 1200
_CONTEXT_SUMMARY_TRUNCATE = 200

_MEMORY_CONTEXT_HEADER = (
    "Background on this student from past conversations, for your own "
    "calibration only. It may be outdated — treat it as a soft hint about "
    "where to focus, never as proof of their current understanding, and "
    "never as authoritative over what they are actually asking right now. "
    "If a note below says they 'understand' something but they ask about "
    "it anyway, explain it in full — do not shorten, skip, or refuse an "
    "explanation because of this background. It never overrides the "
    "student's current question or the active teaching mode; when they "
    "conflict, follow the student. Let this quietly shape tone and "
    "emphasis only — never mention, quote, summarize, or otherwise refer "
    "to this background, this list, or its existence anywhere in your "
    "reply:"
)


def _normalize_topic(topic: str) -> str:
    """Casefold and collapse whitespace, for exact-duplicate comparison only (no fuzzy matching).
    """
    return " ".join(topic.split()).casefold()


class LearningMemoryService:
    """Create, look up, edit, archive/restore and delete learning memories, and
    build the context text injected into a chat's system prompt.
    """

    def __init__(
        self,
        repository: LearningMemoryRepository,
        course_repository: CourseRepository,
        chat_repository: ChatRepository,
    ) -> None:
        self._repository = repository
        self._courses = course_repository
        self._chats = chat_repository

    # --- CRUD ------------------------------------------------------------------

    def create(
        self,
        *,
        topic: str,
        kind: MemoryKind,
        summary: str,
        course_id: str | None = None,
        source_chat_id: str | None = None,
    ) -> LearningMemory:
        topic = self._validate_topic(topic)
        summary = self._validate_summary(summary)
        if course_id is not None and self._courses.get_course(course_id) is None:
            raise CourseNotFoundError(f"No course found with id '{course_id}'.")
        if source_chat_id is not None and self._chats.get_chat(source_chat_id) is None:
            raise ChatNotFoundError(f"No chat found with id '{source_chat_id}'.")

        self._apply_conflict_policy(course_id, topic, kind, exclude_id=None)

        memory_id = str(uuid.uuid4())
        return self._repository.create(
            memory_id, course_id, source_chat_id, topic, kind, summary, DEFAULT_MEMORY_STATUS
        )

    def get(self, memory_id: str) -> LearningMemory:
        memory = self._repository.get(memory_id)
        if memory is None:
            raise MemoryNotFoundError(f"No learning memory found with id '{memory_id}'.")
        return memory

    def list(
        self,
        *,
        course_id: str | None = UNSET,  # type: ignore[assignment]
        kind: MemoryKind | None = None,
        status: MemoryStatus | None = None,
    ) -> list[LearningMemory]:
        return self._repository.list(course_id=course_id, kind=kind, status=status)

    def update(
        self,
        memory_id: str,
        *,
        course_id: str | None = UNSET,  # type: ignore[assignment]
        topic: str | None = None,
        kind: MemoryKind | None = None,
        summary: str | None = None,
    ) -> LearningMemory:
        existing = self.get(memory_id)

        if topic is not None:
            topic = self._validate_topic(topic)
        if summary is not None:
            summary = self._validate_summary(summary)
        if course_id is not UNSET and course_id is not None and self._courses.get_course(course_id) is None:
            raise CourseNotFoundError(f"No course found with id '{course_id}'.")

        if existing.status is MemoryStatus.ACTIVE:
            effective_course_id = existing.course_id if course_id is UNSET else course_id
            effective_topic = topic if topic is not None else existing.topic
            effective_kind = kind if kind is not None else existing.kind
            self._apply_conflict_policy(effective_course_id, effective_topic, effective_kind, exclude_id=memory_id)

        return self._repository.update(memory_id, course_id=course_id, topic=topic, kind=kind, summary=summary)

    def archive(self, memory_id: str) -> LearningMemory:
        self.get(memory_id)  # existence check -> MemoryNotFoundError
        return self._repository.archive(memory_id)

    def restore(self, memory_id: str) -> LearningMemory:
        """Reactivate an archived memory.

        Applies the same conflict policy as ``create``: an active duplicate (same
        topic and kind) raises ``MemoryConflictError``, and an active memory of the
        opposing kind is archived.
        """
        existing = self.get(memory_id)
        self._apply_conflict_policy(existing.course_id, existing.topic, existing.kind, exclude_id=memory_id)
        return self._repository.restore(memory_id)

    def delete(self, memory_id: str) -> None:
        """Permanently delete a memory. Separate from ``archive``."""
        self.get(memory_id)
        self._repository.delete(memory_id)

    # --- conflict / supersession policy ------------------------------------------

    def _apply_conflict_policy(
        self, course_id: str | None, topic: str, kind: MemoryKind, exclude_id: str | None
    ) -> None:
        """Enforce the duplicate and supersession rules within one course (or the global scope).

        * Same normalized topic and same kind already active: raise
          ``MemoryConflictError``; update the existing entry instead.
        * Same topic with an opposing kind active (e.g. ``needs_review`` vs
          ``understands``): archive the superseded memory.
        * Otherwise: no conflict.
        """
        normalized = _normalize_topic(topic)
        active = [
            memory
            for memory in self._repository.list(course_id=course_id, status=MemoryStatus.ACTIVE)
            if memory.id != exclude_id
        ]
        same_topic = [memory for memory in active if _normalize_topic(memory.topic) == normalized]

        same_kind = next((memory for memory in same_topic if memory.kind is kind), None)
        if same_kind is not None:
            raise MemoryConflictError(
                f"An active '{get_kind_info(kind).display_name}' memory already exists for "
                f"'{topic}' in this scope. Edit the existing memory instead of creating a duplicate."
            )

        for memory in same_topic:
            if opposes(memory.kind, kind):
                self._repository.archive(memory.id)

    # --- context for the model ---------------------------------------------------

    def get_active_context_memories(self, course_id: str | None) -> list[LearningMemory]:
        """Active memories relevant to ``course_id``: course-specific first, then global,
        newest first, capped at ``MAX_CONTEXT_ENTRIES``. A General chat (None) gets
        only global memories.
        """
        if course_id is None:
            return self._repository.list(course_id=None, status=MemoryStatus.ACTIVE)[:MAX_CONTEXT_ENTRIES]

        course_specific = self._repository.list(course_id=course_id, status=MemoryStatus.ACTIVE)
        global_memories = self._repository.list(course_id=None, status=MemoryStatus.ACTIVE)
        return (course_specific + global_memories)[:MAX_CONTEXT_ENTRIES]

    def build_memory_context_text(self, course_id: str | None) -> str | None:
        """Return the compact model-facing memory block for this scope, or None if
        nothing is active.

        Bounded by ``MAX_CONTEXT_ENTRIES`` and ``MAX_CONTEXT_CHARS``; never persisted.
        """
        memories = self.get_active_context_memories(course_id)
        return self._compose_context_text(memories)

    @staticmethod
    def _compose_context_text(memories: Sequence[LearningMemory]) -> str | None:
        if not memories:
            return None

        lines = [_MEMORY_CONTEXT_HEADER]
        used_chars = len(_MEMORY_CONTEXT_HEADER)
        included = 0

        for memory in memories:
            summary = " ".join(memory.summary.split())
            if len(summary) > _CONTEXT_SUMMARY_TRUNCATE:
                summary = summary[:_CONTEXT_SUMMARY_TRUNCATE].rstrip() + "…"
            line = f"- {get_kind_info(memory.kind).display_name}: {memory.topic} — {summary}"

            if included > 0 and used_chars + len(line) + 1 > MAX_CONTEXT_CHARS:
                break

            lines.append(line)
            used_chars += len(line) + 1
            included += 1

        if included == 0:
            return None
        return "\n".join(lines)

    # --- validation --------------------------------------------------------------

    @staticmethod
    def _validate_topic(topic: str) -> str:
        normalized = " ".join(topic.split())
        if not normalized:
            raise SessionError("A learning memory topic cannot be empty.")
        if len(normalized) > _MAX_TOPIC_LENGTH:
            raise SessionError(f"Learning memory topic is too long (max {_MAX_TOPIC_LENGTH} characters).")
        return normalized

    @staticmethod
    def _validate_summary(summary: str) -> str:
        # strip() only: a summary may be multiline, so inner whitespace is kept.
        normalized = summary.strip()
        if not normalized:
            raise SessionError("A learning memory summary cannot be empty.")
        if len(normalized) > _MAX_SUMMARY_LENGTH:
            raise SessionError(f"Learning memory summary is too long (max {_MAX_SUMMARY_LENGTH} characters).")
        return normalized
