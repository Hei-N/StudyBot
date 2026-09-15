import pytest

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
