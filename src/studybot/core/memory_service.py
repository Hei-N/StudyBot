"""Learning memory business logic: validation, normalization, the
duplicate/conflict and supersession policy, and the compact context
builder used when composing a chat's system prompt (Stage 6).

Keeps this logic out of the API routes, the SQLite repository (which stays
a dumb data layer, like `ChatRepository`/`CourseRepository`), Flutter, and
`OllamaModel` — none of those know anything about learning memory beyond
"here is some optional text" (see `core.context.build_system_prompt`).

Deliberately NOT here: any automatic extraction of memories from a chat
response. Stage 6 persistence is driven only by explicit user/application
actions (`create`, `update`, `archive`, `restore`, `delete`) — see the
module docstring's "no full automatic extraction yet" note in the spec.
Nothing in this module runs a model or reads chat history.
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

# Deterministic limits for the compact context block injected into a chat's
# system prompt (Stage 6 §13: "impose deterministic limits... maximum
# 10-20 entries or a conservative character/token budget"). Chosen and
# documented here rather than left implicit: at most 12 memories, and the
# composed block (header + bullets) capped around 1200 characters — small
# enough to be cheap for every request, generous enough to matter.
MAX_CONTEXT_ENTRIES = 12
MAX_CONTEXT_CHARS = 1200
_CONTEXT_SUMMARY_TRUNCATE = 200

_MEMORY_CONTEXT_HEADER = (
    "Learning memory (use this to naturally tailor your explanations and "
    "pacing for this student — never mention this list explicitly, and "
    "never say things like \"according to your records\" or \"my notes "
    "say\"):"
)


def _normalize_topic(topic: str) -> str:
    """Casefold + collapse whitespace, for exact-duplicate comparison only
    (Stage 6 §16: "exact normalized topic+kind... is enough for Stage 6" —
    deliberately no fuzzy/semantic matching)."""
    return " ".join(topic.split()).casefold()


class LearningMemoryService:
    """Create, look up, edit, archive/restore, and delete learning
    memories, and build the compact context text `SessionService` injects
    into a chat's system prompt."""

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

        Re-runs the same conflict/supersession policy `create` uses,
        treating "restore" as "make active" — the exact situation that
        policy exists to guard. Restoring a memory whose topic+kind
        already has an active duplicate raises `MemoryConflictError`;
        restoring one whose topic now has an active *opposing* memory
        archives that opposing entry instead, exactly as a fresh `create`
        would.
        """
        existing = self.get(memory_id)
        self._apply_conflict_policy(existing.course_id, existing.topic, existing.kind, exclude_id=memory_id)
        return self._repository.restore(memory_id)

    def delete(self, memory_id: str) -> None:
        """Permanently delete a memory. An explicit, separate action from
        `archive` — see `LearningMemoryRepository.delete`."""
        self.get(memory_id)
        self._repository.delete(memory_id)

    # --- conflict / supersession policy (Stage 6 §16-17) ------------------------

    def _apply_conflict_policy(
        self, course_id: str | None, topic: str, kind: MemoryKind, exclude_id: str | None
    ) -> None:
        """Enforce, within one course (or the global scope), at most one
        *active* memory per normalized topic+kind, and at most one *pole*
        (understands vs. needs-review/misconception) active per topic.

        - An active memory with the same normalized topic and the exact
          same kind already exists: reject with `MemoryConflictError`
          (Stage 6 §16's chosen predictable duplicate rule — update the
          existing entry via `update()` instead of creating a new one).
        - An active memory with the same normalized topic and an
          *opposing* kind exists (e.g. existing `needs_review`, new
          `understands`): archive the superseded one automatically (Stage
          6 §17) rather than letting both stay active forever. History is
          preserved via archiving, never hard-deleted by this policy.
        - Anything else (different topic, or a non-opposing different kind
          such as an existing `needs_review` alongside a new
          `learning_goal`): no conflict, proceed normally.
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

    # --- context for the LLM (Stage 6 §13-14) -----------------------------------

    def get_active_context_memories(self, course_id: str | None) -> list[LearningMemory]:
        """Active memories relevant to `course_id`, course-specific ones
        first (freshest first), then global ones (freshest first),
        capped at `MAX_CONTEXT_ENTRIES`. `course_id=None` (a General chat)
        returns only global memories — there is no "course" to prefer."""
        if course_id is None:
            return self._repository.list(course_id=None, status=MemoryStatus.ACTIVE)[:MAX_CONTEXT_ENTRIES]

        course_specific = self._repository.list(course_id=course_id, status=MemoryStatus.ACTIVE)
        global_memories = self._repository.list(course_id=None, status=MemoryStatus.ACTIVE)
        return (course_specific + global_memories)[:MAX_CONTEXT_ENTRIES]

    def build_memory_context_text(self, course_id: str | None) -> str | None:
        """The compact, model-facing text block for this course (or global
        scope), or `None` if there's nothing active to include — never
        dumps every memory ever created (see `MAX_CONTEXT_ENTRIES`/
        `MAX_CONTEXT_CHARS`). Fed to `core.context.build_system_prompt` as
        its `memory_context` argument; never persisted anywhere."""
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
        # `.strip()` only — unlike topic, a summary may be multiline
        # (Stage 6 §8), so internal whitespace/newlines are preserved.
        normalized = summary.strip()
        if not normalized:
            raise SessionError("A learning memory summary cannot be empty.")
        if len(normalized) > _MAX_SUMMARY_LENGTH:
            raise SessionError(f"Learning memory summary is too long (max {_MAX_SUMMARY_LENGTH} characters).")
        return normalized
