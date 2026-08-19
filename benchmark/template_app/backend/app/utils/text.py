"""Small text helpers used across the app."""

from __future__ import annotations

from datetime import date


def slugify(text: str) -> str:
    """Turn a title into a URL-friendly slug."""
    out = []
    for ch in text.strip().lower():
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("-")
    return "".join(out)


def parse_due_date(value: str | None) -> date | None:
    """Parse an ISO date string; returns None for empty/invalid values."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
