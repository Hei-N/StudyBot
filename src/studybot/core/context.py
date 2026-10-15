"""Builds the system prompt from the baseline instructions plus optional course,
learning-memory and teaching-mode sections.

This is the one place those sections are assembled. Model providers never see
a ``CourseContext`` or ``TeachingMode``; they receive the finished prompt as an
ordinary system message.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CourseContext:
    """The model-facing view of a course: no id or timestamps."""

    name: str
    code: str | None = None
    term: str | None = None
    description: str | None = None


def build_system_prompt(
    baseline_prompt: str,
    course: CourseContext | None,
    mode_instructions: str | None = None,
    memory_context: str | None = None,
) -> str:
    """Combine the baseline prompt with optional course, learning-memory and
    teaching-mode sections.

    The model context is, in order: baseline instructions, course context,
    learning-memory context, teaching-mode instructions, then the chat history and
    newest user message (added by ``ChatService``). Each section is independent and
    may be omitted.

    ``memory_context`` is pre-composed by
    ``LearningMemoryService.build_memory_context_text``; here it is just another
    text section. It comes after ``mode_instructions`` in the signature only so
    existing positional calls keep working.
    """
    parts = [baseline_prompt]

    if course is not None:
        course_lines = ["Current course:", course.name]
        if course.code:
            course_lines.append(f"Course code: {course.code}")
        if course.term:
            course_lines.append(f"Term: {course.term}")
        if course.description:
            course_lines.append(f"Description: {course.description}")
        parts.append("\n".join(course_lines))

    if memory_context:
        parts.append(memory_context)

    if mode_instructions:
        parts.append(mode_instructions)

    return "\n\n".join(parts)
