"""Domain object to transport DTO conversion.

The only place that knows both the domain types and ``api.schemas``.
"""

from __future__ import annotations

import base64

from studybot.api.schemas import (
    AttachmentOut,
    AuthorizationOut,
    ChatOut,
    CourseOut,
    LearningMemoryOut,
    LibraryFileOut,
    LibrarySourceOut,
    MemoryKindInfoOut,
    MessageOut,
    ModeInfoOut,
)
from studybot.core.learning_memory import MemoryKindInfo
from studybot.core.reasoning_mode import ReasoningModeInfo
from studybot.core.teaching_mode import TeachingModeInfo
from studybot.storage.base import (
    ChatSession,
    Course,
    LearningMemory,
    LibraryFile,
    LibrarySource,
    LibrarySourceAuthorization,
    MessageRecord,
)


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
        attachments=[
            AttachmentOut(
                id=a.id,
                file_id=a.file_id,
                display_name=a.display_name,
                page_count=a.page_count,
                text_page_count=a.text_page_count,
                processing_state=a.processing_state,
            )
            for a in record.attachments
        ],
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


def library_source_to_out(source: LibrarySource, has_authorization: bool) -> LibrarySourceOut:
    return LibrarySourceOut(
        id=source.id,
        course_id=source.course_id,
        kind=source.kind.value,
        display_name=source.display_name,
        locator=source.locator,
        created_at=source.created_at,
        updated_at=source.updated_at,
        has_authorization=has_authorization,
    )


def authorization_to_out(authorization: LibrarySourceAuthorization) -> AuthorizationOut:
    return AuthorizationOut(
        source_id=authorization.source_id,
        platform=authorization.platform,
        kind=authorization.kind,
        payload=base64.b64encode(authorization.payload).decode("ascii"),
    )


def library_file_to_out(file: LibraryFile, *, hide_path: bool = False) -> LibraryFileOut:
    """``hide_path`` shows the original filename instead of the private stored name (uploads)."""
    return LibraryFileOut(
        id=file.id,
        source_id=file.source_id,
        relative_path=file.display_name if hide_path else file.relative_path,
        display_name=file.display_name,
        extension=file.extension,
        size_bytes=file.size_bytes,
        processing_state=file.processing_state.value,
        failure_code=file.failure_code,
        page_count=file.page_count,
        text_page_count=file.text_page_count,
        processing_version=file.processing_version,
        indexed_at=file.indexed_at,
        updated_at=file.updated_at,
    )
