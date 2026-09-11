from studybot.core.titles import generate_title


def test_short_message_is_used_as_is():
    assert generate_title("Explain vectors") == "Explain vectors"


def test_collapses_internal_whitespace_and_newlines():
    assert generate_title("Explain   vectors\n\nplease") == "Explain vectors please"


def test_strips_leading_and_trailing_whitespace():
    assert generate_title("   Explain vectors   ") == "Explain vectors"


def test_long_message_is_truncated_on_a_word_boundary():
    message = "Explain Newton's second law and why acceleration changes with force"

    title = generate_title(message)

    assert len(title) <= 41  # max length + ellipsis
    assert title.endswith("…")
    assert not title[:-1].endswith(" ")
    assert message.startswith(title[:-1].rstrip())


def test_truncation_never_splits_a_word_when_a_space_exists():
    message = "a" * 30 + " " + "b" * 30
    title = generate_title(message)
    assert "a" * 30 in title
    assert "b" * 30 not in title


def test_empty_message_falls_back_to_untitled():
    assert generate_title("") == "Untitled"


def test_whitespace_only_message_falls_back_to_untitled():
    assert generate_title("   \n\t  ") == "Untitled"


def test_is_deterministic():
    message = "Explain the difference between speed and velocity"
    assert generate_title(message) == generate_title(message)


def test_handles_unicode_and_burmese_content():
    message = "မြန်မာလို အရှိန်နဲ့ velocity ကို ရှင်းပြပါ"
    title = generate_title(message)
    assert title  # produces some non-empty, non-crashing result
    assert "Untitled" != title
