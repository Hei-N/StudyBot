"""Composes the effective system prompt from Study Bot's baseline
instructions plus optional course context and teaching-mode instructions.

Kept separate from the baseline prompt (`core/prompts.py`), the per-mode
text (`core/mode_prompts.py`), and any model provider, so this stays the
one place that assembles them — no scattered string concatenation
elsewhere. `ModelProvider` implementations never see a `CourseContext` or a
`TeachingMode`; they only ever receive the fully composed prompt as an
ordinary system `Message`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CourseContext:
    """The minimal, model-facing view of a course: no id, no timestamps —
    only what's useful for the model to know it's currently discussing."""

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
    """Combine the baseline instructions with optional course context,
    optional teaching-mode instructions, and optional learning-memory
    context (Stage 6).

    The effective model context ends up, in order:
        1. baseline Study Bot instructions (`baseline_prompt`)
        2. minimal course context (`course`, if any)
        3. learning-memory context (`memory_context`, if any)
        4. teaching-mode instructions (`mode_instructions`, if any)
        5. chat conversation history (added by `ChatService`, not here)
        6. newest user message (added by `ChatService`, not here)
    Every section is independent — none overwrites another, and any may be
    omitted without affecting the others. `memory_context` is a new
    parameter appended after `mode_instructions` (rather than inserted
    between `course` and `mode_instructions` positionally) purely so every
    existing positional call site keeps working unchanged; its *place in
    the composed text* is still between course and mode, per Stage 6's
    spec ("baseline, course, learning memory, teaching mode").
    `memory_context` is pre-composed by
    `core.memory_service.LearningMemoryService.build_memory_context_text`
    — this function does not know what a "learning memory" is, only that
    it's one more optional text section, exactly like `mode_instructions`.
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
