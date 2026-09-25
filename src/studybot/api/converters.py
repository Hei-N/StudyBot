"""Domain object → transport DTO conversion.

The only place that knows both the domain dataclasses (`storage.base`,
`core.teaching_mode`) and the transport schemas (`api.schemas`). Route
handlers call these rather than constructing DTOs field-by-field inline.
"""

from __future__ import annotations

from studybot.api.schemas import ChatOut, CourseOut, LearningMemoryOut, MemoryKindInfoOut, MessageOut, ModeInfoOut
from studybot.core.learning_memory import MemoryKindInfo
from studybot.core.reasoning_mode import ReasoningModeInfo
from studybot.core.teaching_mode import TeachingModeInfo
from studybot.storage.base import ChatSession, Course, LearningMemory, MessageRecord


def course_to_out(course: Course) -> CourseOut:
    return CourseOut(
        id=course.id,
        name=course.name,
        code=course.code,
        term=course.term,
        description=course.description,
        created_at=course.created_at,
        updated_at=course.updated_at,
    )


def chat_to_out(chat: ChatSession) -> ChatOut:
    return ChatOut(
        id=chat.id,
        title=chat.title,
        course_id=chat.course_id,
        teaching_mode=chat.teaching_mode.value,
        reasoning_mode=chat.reasoning_mode.value,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def message_record_to_out(record: MessageRecord) -> MessageOut:
    return MessageOut(
        id=record.id,
        role=record.role.value,
        content=record.content,
        created_at=record.created_at,
    )


def mode_info_to_out(info: TeachingModeInfo) -> ModeInfoOut:
    return ModeInfoOut(id=info.mode.value, display_name=info.display_name, description=info.description)


def reasoning_mode_info_to_out(info: ReasoningModeInfo) -> ModeInfoOut:
    return ModeInfoOut(id=info.mode.value, display_name=info.display_name, description=info.description)


def memory_kind_info_to_out(info: MemoryKindInfo) -> MemoryKindInfoOut:
    return MemoryKindInfoOut(id=info.kind.value, display_name=info.display_name, description=info.description)


def learning_memory_to_out(memory: LearningMemory) -> LearningMemoryOut:
    return LearningMemoryOut(
        id=memory.id,
        course_id=memory.course_id,
        source_chat_id=memory.source_chat_id,
        topic=memory.topic,
        kind=memory.kind.value,
        summary=memory.summary,
        status=memory.status.value,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )
