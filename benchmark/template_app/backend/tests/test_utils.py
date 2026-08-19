"""Text helper tests."""

from datetime import date

from app.utils.text import parse_due_date, slugify


def test_slugify_basic():
    assert slugify("Hello World") == "hello-world"


def test_slugify_lowercases():
    assert slugify("Sprint") == "sprint"


def test_slugify_alnum_passthrough():
    assert slugify("abc123") == "abc123"


def test_parse_due_date_valid():
    assert parse_due_date("2026-01-15") == date(2026, 1, 15)


def test_parse_due_date_none_and_empty():
    assert parse_due_date(None) is None
    assert parse_due_date("") is None


def test_parse_due_date_invalid():
    assert parse_due_date("not-a-date") is None
