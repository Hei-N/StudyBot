import pytest

from studybot.core.reasoning_mode import (
    DEFAULT_REASONING_MODE,
    ReasoningMode,
    all_modes,
    get_mode_info,
    parse_reasoning_mode,
)


def test_both_modes_exist():
    assert {m.value for m in ReasoningMode} == {"fast", "deep"}


def test_default_mode_is_fast():
    assert DEFAULT_REASONING_MODE is ReasoningMode.FAST


def test_stable_identifiers_are_lowercase_strings():
    for mode in ReasoningMode:
        assert mode.value == mode.value.lower()
        assert isinstance(mode.value, str)


def test_all_modes_returns_display_metadata_for_every_mode():
    infos = all_modes()

    assert len(infos) == 2
    assert {info.mode for info in infos} == set(ReasoningMode)
    for info in infos:
        assert info.display_name
        assert info.description


def test_get_mode_info_matches_all_modes_entry():
    info = get_mode_info(ReasoningMode.DEEP)

    assert info.mode is ReasoningMode.DEEP
    assert info.display_name == "Deep Think"


def test_fast_display_name():
    assert get_mode_info(ReasoningMode.FAST).display_name == "Fast"


def test_parse_reasoning_mode_accepts_stable_identifiers():
    for mode in ReasoningMode:
        assert parse_reasoning_mode(mode.value) is mode


def test_parse_reasoning_mode_is_case_and_whitespace_insensitive():
    assert parse_reasoning_mode("  FAST  ") is ReasoningMode.FAST
    assert parse_reasoning_mode("Deep") is ReasoningMode.DEEP


def test_parse_reasoning_mode_rejects_unknown_value():
    with pytest.raises(ValueError):
        parse_reasoning_mode("not-a-real-mode")


def test_parse_reasoning_mode_rejects_empty_string():
    with pytest.raises(ValueError):
        parse_reasoning_mode("")
