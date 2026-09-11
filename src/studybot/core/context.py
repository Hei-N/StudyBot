"""Composes the effective system prompt from Study Bot's baseline
instructions plus optional course context.

Kept separate from both the baseline prompt (`core/prompts.py`) and any
model provider, so a future stage's teaching-mode prompts can extend this
one composition point instead of scattering string concatenation across the
codebase. `ModelProvider` implementations never see a `CourseContext` —
they only ever receive the fully composed prompt as an ordinary system
`Message`.
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


def build_system_prompt(baseline_prompt: str, course: CourseContext | None) -> str:
    """Combine the baseline instructions with optional course context.

    The effective model context ends up, in order:
        1. baseline Study Bot instructions (this function's `baseline_prompt`)
        2. minimal course context (this function's `course`, if any)
        3. chat conversation history (added by `ChatService`, not here)
        4. newest user message (added by `ChatService`, not here)
    """
    if course is None:
        return baseline_prompt

    lines = [baseline_prompt, "", "Current course:", course.name]
    if course.code:
        lines.append(f"Course code: {course.code}")
    if course.term:
        lines.append(f"Term: {course.term}")
    if course.description:
        lines.append(f"Description: {course.description}")
    return "\n".join(lines)
