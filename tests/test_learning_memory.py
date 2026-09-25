import pytest

from studybot.core.learning_memory import (
    DEFAULT_MEMORY_STATUS,
    MemoryKind,
    MemoryStatus,
    all_kinds,
    get_kind_info,
    opposes,
    parse_memory_kind,
    parse_memory_status,
)


def test_default_memory_status_is_active():
    assert DEFAULT_MEMORY_STATUS is MemoryStatus.ACTIVE


def test_all_five_kinds_exist():
    ids = {kind.value for kind in MemoryKind}
    assert ids == {"understands", "needs_review", "misconception", "learning_goal", "useful_strategy"}


def test_kinds_have_stable_identifiers():
    assert MemoryKind.UNDERSTANDS.value == "understands"
    assert MemoryKind.NEEDS_REVIEW.value == "needs_review"
    assert MemoryKind.MISCONCEPTION.value == "misconception"
    assert MemoryKind.LEARNING_GOAL.value == "learning_goal"
    assert MemoryKind.USEFUL_STRATEGY.value == "useful_strategy"


def test_all_kinds_returns_five_with_metadata():
    infos = all_kinds()
    assert len(infos) == 5
    for info in infos:
        assert info.display_name
        assert info.description


def test_all_kinds_uses_natural_language_display_names_not_raw_ids():
    display_names = {info.display_name for info in all_kinds()}
    assert "Needs review" in display_names
    assert "Understands" in display_names
    assert "Misconception" in display_names
    assert "Goal" in display_names
    assert "Helpful approach" in display_names
    # None of the raw enum identifiers leak through as a display name.
    assert "needs_review" not in display_names


def test_get_kind_info_correctness():
    info = get_kind_info(MemoryKind.NEEDS_REVIEW)
    assert info.kind is MemoryKind.NEEDS_REVIEW
    assert info.display_name == "Needs review"


def test_parse_memory_kind_case_and_whitespace_insensitive():
    assert parse_memory_kind("needs_review") is MemoryKind.NEEDS_REVIEW
    assert parse_memory_kind("  NEEDS_REVIEW ") is MemoryKind.NEEDS_REVIEW
    assert parse_memory_kind("Understands") is MemoryKind.UNDERSTANDS


def test_parse_memory_kind_rejects_unknown():
    with pytest.raises(ValueError):
        parse_memory_kind("mastery_percentage")


def test_parse_memory_kind_rejects_empty():
    with pytest.raises(ValueError):
        parse_memory_kind("")


def test_parse_memory_status_roundtrip():
    assert parse_memory_status("active") is MemoryStatus.ACTIVE
    assert parse_memory_status("ARCHIVED") is MemoryStatus.ARCHIVED


def test_parse_memory_status_rejects_unknown():
    with pytest.raises(ValueError):
        parse_memory_status("deleted")


# --- opposes() (conflict/supersession policy building block) --------------------------


def test_understands_opposes_needs_review():
    assert opposes(MemoryKind.UNDERSTANDS, MemoryKind.NEEDS_REVIEW)
    assert opposes(MemoryKind.NEEDS_REVIEW, MemoryKind.UNDERSTANDS)


def test_understands_opposes_misconception():
    assert opposes(MemoryKind.UNDERSTANDS, MemoryKind.MISCONCEPTION)
    assert opposes(MemoryKind.MISCONCEPTION, MemoryKind.UNDERSTANDS)


def test_needs_review_and_misconception_do_not_oppose_each_other():
    """Both are on the same 'needs attention' pole."""
    assert not opposes(MemoryKind.NEEDS_REVIEW, MemoryKind.MISCONCEPTION)
    assert not opposes(MemoryKind.MISCONCEPTION, MemoryKind.NEEDS_REVIEW)


def test_same_kind_never_opposes_itself():
    for kind in MemoryKind:
        assert not opposes(kind, kind)


def test_learning_goal_and_useful_strategy_oppose_nothing():
    neutral = [MemoryKind.LEARNING_GOAL, MemoryKind.USEFUL_STRATEGY]
    for neutral_kind in neutral:
        for other in MemoryKind:
            assert not opposes(neutral_kind, other)
            assert not opposes(other, neutral_kind)
