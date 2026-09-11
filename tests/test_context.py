import dataclasses

from studybot.core.context import CourseContext, build_system_prompt


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
