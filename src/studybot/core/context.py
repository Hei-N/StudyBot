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
) -> str:
    """Combine the baseline instructions with optional course context and
    optional teaching-mode instructions.

    The effective model context ends up, in order:
        1. baseline Study Bot instructions (`baseline_prompt`)
        2. minimal course context (`course`, if any)
        3. teaching-mode instructions (`mode_instructions`, if any)
        4. chat conversation history (added by `ChatService`, not here)
        5. newest user message (added by `ChatService`, not here)
    Course and mode are independent sections — neither overwrites the
    other, and either may be omitted without affecting the other.
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

    if mode_instructions:
        parts.append(mode_instructions)

    return "\n\n".join(parts)
