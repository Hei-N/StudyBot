"""Tests for the reasoning/answer separation filter and the stored-reply classifier, in isolation.
"""

import pytest

from studybot.core.exceptions import ModelError, UnsafeModelOutputError
from studybot.core.output_integrity import (
    HistoryVerdict,
    ReasoningOutputFilter,
    assess_stored_reply,
    filter_complete_output,
    strip_confident_reasoning,
)

SECRET = "SECRET-REASONING"


def run(chunks, **kwargs):
    """Feed chunks; return (list of released pieces, joined output)."""
    output_filter = ReasoningOutputFilter(**kwargs)
    released = [output_filter.feed(c) for c in chunks]
    released.append(output_filter.finish())
    return released, "".join(released)


def every_split(text):
    """All two-way splits, plus every fixed chunk size."""
    for cut in range(len(text) + 1):
        yield [text[:cut], text[cut:]]
    for size in range(1, len(text) + 1):
        yield [text[i : i + size] for i in range(0, len(text), size)]


def assert_never_released(released, forbidden):
    so_far = ""
    for piece in released:
        so_far += piece
        for token in forbidden:
            assert token not in so_far


# --- clean output ---------------------------------------------------------------


def test_plain_answer_passes_through_unchanged():
    _, out = run(["Density is ", "mass / volume."])
    assert out == "Density is mass / volume."


def test_plain_answer_is_released_progressively():
    released, _ = run(["Hello", " world", ", friend"])
    assert released[:3] == ["Hello", " world", ", friend"]


def test_empty_chunks_are_ignored():
    _, out = run(["", "Hi", "", "", " there", ""])
    assert out == "Hi there"


def test_step_by_step_explanations_are_untouched():
    text = "Step 1: identify knowns.\nStep 2: pick a formula.\n\nFirst, let me explain why v = u + at works."
    _, out = run([text])
    assert out == text


def test_filter_is_a_model_error_subtype():
    assert issubclass(UnsafeModelOutputError, ModelError)


# --- leading reasoning span ---------------------------------------------------------


@pytest.mark.parametrize("chunks", list(every_split(f"<think>\n{SECRET}\n</think>\n\nThe answer is 4.")))
def test_leading_span_is_removed_at_every_split(chunks):
    released, out = run(chunks)
    assert out == "The answer is 4."
    assert_never_released(released, [SECRET, "<think", "</think"])


def test_leading_whitespace_before_span_is_tolerated():
    _, out = run(["\n  ", "<think>x</think>", "Answer"])
    assert out == "Answer"


def test_multiple_leading_spans_are_all_removed():
    _, out = run([f"<think>{SECRET}</think>\n<think>{SECRET}</think>\nFinal."])
    assert out == "Final."


def test_empty_leading_span_is_removed():
    _, out = run(["<think>\n\n</think>\n\nJust the answer."])
    assert out == "Just the answer."


def test_reasoning_text_is_not_retained_in_memory():
    output_filter = ReasoningOutputFilter()
    output_filter.feed("<think>")
    for _ in range(1000):
        output_filter.feed("lots of reasoning ")
    assert len(output_filter._pending) < len("</think>")
    assert output_filter.stats.reasoning_chars_discarded > 10000


def test_stats_count_spans_without_content():
    output_filter = ReasoningOutputFilter()
    output_filter.feed("<think>abc</think>Answer")
    output_filter.finish()
    stats = output_filter.stats
    assert stats.reasoning_spans == 1
    assert stats.visible_chars == len("Answer")


# --- fail closed ------------------------------------------------------------------------


def test_unterminated_span_fails_closed_without_releasing_anything():
    output_filter = ReasoningOutputFilter()
    assert output_filter.feed(f"<think>{SECRET} still thinking") == ""
    with pytest.raises(UnsafeModelOutputError):
        output_filter.finish()


@pytest.mark.parametrize("chunks", list(every_split(f"{SECRET} planning\n</think>\n\nAnswer")))
def test_bare_close_marker_in_prose_fails_closed(chunks):
    with pytest.raises(UnsafeModelOutputError):
        run(chunks)


def test_close_marker_glued_to_text_fails_closed():
    with pytest.raises(UnsafeModelOutputError):
        run(["I will answer now.</think>The answer."])


def test_second_span_after_answer_fails_closed():
    with pytest.raises(UnsafeModelOutputError):
        run(["<think>a</think>Answer part.\n<think>more</think>\nMore."])


def test_marker_is_never_released_before_failing():
    output_filter = ReasoningOutputFilter()
    released = output_filter.feed("Answer\n</thi")
    assert "<" not in released
    with pytest.raises(UnsafeModelOutputError):
        output_filter.feed("nk>\n")


@pytest.mark.parametrize("text", ["", "   \n\n ", "<think>only reasoning</think>", "<think>x</think>\n\n  "])
def test_no_visible_answer_fails_closed(text):
    with pytest.raises(UnsafeModelOutputError):
        run([text])


def test_feed_after_finish_is_rejected():
    output_filter = ReasoningOutputFilter()
    output_filter.feed("Hi")
    output_filter.finish()
    with pytest.raises(RuntimeError):
        output_filter.feed("more")


# --- legitimate literal tags ------------------------------------------------------------


def test_close_tag_in_inline_code_passes():
    text = "Qwen ends its reasoning with `</think>` before answering."
    _, out = run([text])
    assert out == text


@pytest.mark.parametrize("chunks", list(every_split("Example:\n```xml\n<think>\nplan\n</think>\n```\nDone.")))
def test_tags_inside_fenced_code_pass_at_every_split(chunks):
    _, out = run(chunks)
    assert out == "Example:\n```xml\n<think>\nplan\n</think>\n```\nDone."


def test_tags_inside_tilde_fence_pass():
    text = "~~~\n</think>\n~~~\nok"
    _, out = run([text])
    assert out == text


def test_close_tag_after_fence_closes_is_caught():
    with pytest.raises(UnsafeModelOutputError):
        run(["```\ncode\n```\n</think>\nAnswer"])


def test_double_backtick_inline_code_passes():
    text = "Write ``</think>`` literally."
    _, out = run([text])
    assert out == text


def test_unmatched_backtick_does_not_hide_a_marker():
    with pytest.raises(UnsafeModelOutputError):
        run(["it`s done </think> answer"])


def test_open_tag_mid_answer_is_literal_text():
    text = "The template inserts <think> at the start of generation."
    _, out = run([text])
    assert out == text


# --- implicit (no opening tag) mode --------------------------------------------------


@pytest.mark.parametrize("chunks", list(every_split(f"{SECRET} planning...\n</think>\n\nAnswer here.")))
def test_implicit_mode_strips_untagged_leading_reasoning(chunks):
    released, out = run(chunks, implicit_open=True)
    assert out == "Answer here."
    assert_never_released(released, [SECRET])


def test_implicit_mode_without_marker_treats_all_as_answer():
    _, out = run(["Just an", " answer."], implicit_open=True)
    assert out == "Just an answer."


def test_implicit_mode_buffers_until_the_end():
    output_filter = ReasoningOutputFilter(implicit_open=True)
    assert output_filter.feed("could be reasoning") == ""
    assert output_filter.finish() == "could be reasoning"


def test_filter_complete_output_matches_streaming():
    text = f"<think>{SECRET}</think>\nAnswer."
    assert filter_complete_output(text) == run([text[i : i + 2] for i in range(0, len(text), 2)])[1]


# --- stored replies --------------------------------------------------------------------


def test_clean_reply_is_clean():
    assert assess_stored_reply("Density = m / V.").verdict is HistoryVerdict.CLEAN


def test_code_sample_with_tags_is_clean():
    assert assess_stored_reply("```\n<think>\n</think>\n```").verdict is HistoryVerdict.CLEAN


def test_bare_close_line_reply_is_contaminated_and_repairable():
    assessment = assess_stored_reply(f"Okay, {SECRET}.\nPlan...\n</think>\n\nHello! What topic?")
    assert assessment.verdict is HistoryVerdict.CONTAMINATED
    assert assessment.repaired == "Hello! What topic?"
    assert assessment.removed_chars > 0


def test_leading_span_reply_is_contaminated():
    assessment = assess_stored_reply(f"<think>{SECRET}</think>\n\nAnswer.")
    assert assessment.verdict is HistoryVerdict.CONTAMINATED
    assert assessment.repaired == "Answer."


@pytest.mark.parametrize(
    "content",
    [
        "a\n</think>\nb\n</think>\nc",  # two markers
        "Reasoning</think>Answer",  # marker not alone on its line
        "plan\n</think>\n",  # nothing after the marker
        "<think>never closed",  # unterminated
    ],
)
def test_uncertain_replies_are_ambiguous_and_left_alone(content):
    assert assess_stored_reply(content).verdict is HistoryVerdict.AMBIGUOUS
    assert strip_confident_reasoning(content) == content


def test_strip_confident_reasoning_returns_same_object_for_clean_text():
    text = "Clean answer."
    assert strip_confident_reasoning(text) is text
