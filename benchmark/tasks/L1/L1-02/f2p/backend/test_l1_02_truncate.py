from app.utils.text import truncate


def test_short_text_unchanged():
    assert truncate("hello", 10) == "hello"
    assert truncate("exact fit!", 10) == "exact fit!"


def test_result_length_bounded():
    text = "the quick brown fox jumps over the lazy dog"
    for n in (8, 12, 20, 30):
        assert len(truncate(text, n)) <= n


def test_ends_with_ellipsis_when_truncated():
    assert truncate("hello world again", 12).endswith("…")


def test_word_boundary_examples():
    assert truncate("hello world again", 12) == "hello world…"
    assert truncate("hello world again", 9) == "hello…"


def test_never_cuts_word_in_half():
    text = "alpha bravo charlie delta"
    for n in (10, 15, 22):
        out = truncate(text, n)
        prefix = out[:-1].rstrip()  # drop the ellipsis
        assert text.startswith(prefix)
        # the character after the prefix in the original must be a space
        # (i.e. the prefix ends exactly at a word boundary)
        assert prefix == "" or text[len(prefix)] == " "
