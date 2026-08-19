from app.utils.text import slugify


def test_collapses_consecutive_separators():
    assert slugify("Hello,  World!") == "hello-world"


def test_strips_edge_hyphens():
    assert slugify("  --Weird__Name--  ") == "weird-name"


def test_mixed_punctuation_runs():
    assert slugify("a...b---c") == "a-b-c"


def test_clean_input_unchanged():
    assert slugify("Hello World") == "hello-world"
    assert slugify("abc123") == "abc123"


def test_all_separators_becomes_empty():
    assert slugify("!!!") == ""
