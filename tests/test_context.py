import dataclasses

from studybot.core.context import CourseContext, build_system_prompt
from studybot.core.mode_prompts import get_mode_prompt
from studybot.core.teaching_mode import TeachingMode


def test_no_course_returns_baseline_unchanged():
    assert build_system_prompt("Baseline instructions.", None) == "Baseline instructions."


def test_course_context_is_appended_after_baseline():
    context = CourseContext(name="University Physics I", code="PHY 215", term="Fall 2026")

    prompt = build_system_prompt("Baseline.", context)

    assert prompt.startswith("Baseline.")
    assert "Current course:" in prompt
    assert "University Physics I" in prompt
    assert "PHY 215" in prompt
    assert "Fall 2026" in prompt


def test_only_present_fields_are_included():
    context = CourseContext(name="Calculus III")

    prompt = build_system_prompt("Baseline.", context)

    assert "Calculus III" in prompt
    assert "Course code" not in prompt
    assert "Term:" not in prompt
    assert "Description:" not in prompt


def test_description_is_included_when_present():
    context = CourseContext(name="Chemistry", description="Intro to reactions")

    prompt = build_system_prompt("Baseline.", context)

    assert "Intro to reactions" in prompt


def test_never_includes_ids_or_timestamps():
    # CourseContext structurally has no id/timestamp fields at all, so this
    # documents the guarantee rather than testing an evasion of it.
    context = CourseContext(name="Physics", code="PHY 215", term="Fall 2026", description="desc")

    prompt = build_system_prompt("Baseline.", context)

    field_names = {f.name for f in dataclasses.fields(context)}
    assert field_names == {"name", "code", "term", "description"}


def test_supports_unicode_and_burmese_course_names():
    context = CourseContext(name="ရူပဗေဒ")

    prompt = build_system_prompt("Baseline.", context)

    assert "ရူပဗေဒ" in prompt


def test_is_deterministic():
    context = CourseContext(name="Physics", code="PHY 215")

    first = build_system_prompt("Baseline.", context)
    second = build_system_prompt("Baseline.", context)

    assert first == second


# --- teaching-mode composition -------------------------------------------------------


def test_mode_instructions_appended_with_no_course():
    homework_prompt = get_mode_prompt(TeachingMode.HOMEWORK)

    prompt = build_system_prompt("Baseline.", None, homework_prompt)

    assert prompt.startswith("Baseline.")
    assert homework_prompt in prompt


def test_course_and_mode_compose_without_overwriting_each_other():
    course = CourseContext(name="University Physics I", code="PHY 215")
    homework_prompt = get_mode_prompt(TeachingMode.HOMEWORK)

    prompt = build_system_prompt("Baseline.", course, homework_prompt)

    assert "Baseline." in prompt
    assert "University Physics I" in prompt
    assert "PHY 215" in prompt
    assert homework_prompt in prompt


def test_only_the_active_modes_instructions_are_present():
    homework_prompt = get_mode_prompt(TeachingMode.HOMEWORK)
    quick_prompt = get_mode_prompt(TeachingMode.QUICK)

    prompt = build_system_prompt("Baseline.", None, homework_prompt)

    assert homework_prompt in prompt
    assert quick_prompt not in prompt


def test_switching_mode_drops_the_previous_modes_text():
    course = CourseContext(name="University Physics I", code="PHY 215")
    homework = build_system_prompt("Baseline.", course, get_mode_prompt(TeachingMode.HOMEWORK))
    quick = build_system_prompt("Baseline.", course, get_mode_prompt(TeachingMode.QUICK))

    assert get_mode_prompt(TeachingMode.HOMEWORK) not in quick
    assert get_mode_prompt(TeachingMode.QUICK) in quick
    # Course context is unaffected by the mode switch.
    assert "University Physics I" in homework
    assert "University Physics I" in quick


def test_no_mode_instructions_means_no_mode_section():
    prompt = build_system_prompt("Baseline.", None, None)

    assert prompt == "Baseline."
    assert "Teaching mode" not in prompt


def test_every_modes_prompt_is_distinct_and_non_empty():
    prompts = [get_mode_prompt(mode) for mode in TeachingMode]

    assert all(p.strip() for p in prompts)
    assert len(set(prompts)) == len(prompts)


# --- learning-memory composition (Stage 6) ----------------------------------------------


def test_memory_context_appears_between_course_and_mode():
    course = CourseContext(name="Physics")
    homework_prompt = get_mode_prompt(TeachingMode.HOMEWORK)
    memory_text = "Learning memory:\n- Needs review: Vectors — mixes x/y."

    prompt = build_system_prompt("Baseline.", course, homework_prompt, memory_context=memory_text)

    course_index = prompt.index("Physics")
    memory_index = prompt.index("Learning memory:")
    mode_index = prompt.index(homework_prompt)
    assert course_index < memory_index < mode_index


def test_memory_context_with_no_course_still_appears():
    homework_prompt = get_mode_prompt(TeachingMode.HOMEWORK)
    memory_text = "Learning memory:\n- Goal: review Newton's laws."

    prompt = build_system_prompt("Baseline.", None, homework_prompt, memory_context=memory_text)

    assert "Learning memory:" in prompt
    assert prompt.index("Learning memory:") < prompt.index(homework_prompt)


def test_no_memory_context_means_no_memory_section():
    prompt = build_system_prompt("Baseline.", None, None, memory_context=None)

    assert prompt == "Baseline."


def test_omitting_memory_context_keyword_preserves_old_three_arg_behavior():
    """Every pre-Stage-6 positional call site (`build_system_prompt(base,
    course, mode_instructions)`) must keep working unchanged."""
    course = CourseContext(name="Physics")
    homework_prompt = get_mode_prompt(TeachingMode.HOMEWORK)

    with_memory_none = build_system_prompt("Baseline.", course, homework_prompt)
    with_explicit_none = build_system_prompt("Baseline.", course, homework_prompt, memory_context=None)
    assert with_memory_none == with_explicit_none


def test_memory_context_and_course_and_mode_all_compose_independently():
    course = CourseContext(name="Physics", code="PHY 215")
    homework_prompt = get_mode_prompt(TeachingMode.HOMEWORK)
    memory_text = "Learning memory:\n- Needs review: Vectors — mixes x/y."

    prompt = build_system_prompt("Baseline.", course, homework_prompt, memory_context=memory_text)

    assert "Baseline." in prompt
    assert "Physics" in prompt
    assert "PHY 215" in prompt
    assert memory_text in prompt
    assert homework_prompt in prompt
