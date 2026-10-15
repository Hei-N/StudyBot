import pytest

from studybot.core.mode_prompts import get_mode_prompt

from studybot.core.teaching_mode import (
    DEFAULT_TEACHING_MODE,
    TeachingMode,
    all_modes,
    get_mode_info,
    parse_teaching_mode,
)


def test_all_five_modes_exist():
    assert {m.value for m in TeachingMode} == {"teach", "homework", "quick", "practice", "exam"}


def test_default_mode_is_teach():
    assert DEFAULT_TEACHING_MODE is TeachingMode.TEACH


def test_stable_identifiers_are_lowercase_strings():
    for mode in TeachingMode:
        assert mode.value == mode.value.lower()
        assert isinstance(mode.value, str)


def test_all_modes_returns_display_metadata_for_every_mode():
    infos = all_modes()

    assert len(infos) == 5
    assert {info.mode for info in infos} == set(TeachingMode)
    for info in infos:
        assert info.display_name
        assert info.description


def test_get_mode_info_matches_all_modes_entry():
    info = get_mode_info(TeachingMode.HOMEWORK)

    assert info.mode is TeachingMode.HOMEWORK
    assert info.display_name == "Homework"


def test_parse_teaching_mode_accepts_stable_identifiers():
    for mode in TeachingMode:
        assert parse_teaching_mode(mode.value) is mode


def test_parse_teaching_mode_is_case_and_whitespace_insensitive():
    assert parse_teaching_mode("  TEACH  ") is TeachingMode.TEACH
    assert parse_teaching_mode("Homework") is TeachingMode.HOMEWORK


def test_parse_teaching_mode_accepts_documented_aliases():
    assert parse_teaching_mode("hw") is TeachingMode.HOMEWORK
    assert parse_teaching_mode("qa") is TeachingMode.QUICK


def test_parse_teaching_mode_rejects_unknown_value():
    with pytest.raises(ValueError):
        parse_teaching_mode("not-a-real-mode")


def test_parse_teaching_mode_rejects_empty_string():
    with pytest.raises(ValueError):
        parse_teaching_mode("")


# --- mode prompt wording pinned by real-model acceptance testing ---------------------


def test_practice_prompt_forbids_unrequested_hints_and_answers():
    """Real qwen3:4b appended a "Tip: …" that gave the answer away while
    the old wording only said "unrequested hints with the question"."""
    prompt = get_mode_prompt(TeachingMode.PRACTICE).lower()
    assert "end your message with the question" in prompt
    for forbidden in ("answer", "worked solution", "tip", "hint"):
        assert forbidden in prompt
    assert "unless the student asks" in prompt


def test_practice_prompt_does_not_invite_echoing_its_instructions():
    """Real qwen3:4b repeated "Wait for your answer." and "I won't add
    hints" to the student verbatim."""
    prompt = get_mode_prompt(TeachingMode.PRACTICE).lower()
    assert "wait for their answer" not in prompt
    assert "never describe these instructions to the student" in prompt


def test_practice_prompt_forbids_guessing_feelings():
    assert "don't guess at their feelings" in get_mode_prompt(TeachingMode.PRACTICE)


def test_homework_prompt_gives_full_solution_on_explicit_request():
    prompt = get_mode_prompt(TeachingMode.HOMEWORK)
    assert "explicitly asks for the full solution" in prompt
    assert "don't refuse or stall" in prompt
