"""Playwright F2P: overdue cards carry class, red left border, and badge."""

import os

import pytest
from playwright.sync_api import sync_playwright

FREEZE_CSS = "*, *::before, *::after { transition: none !important; animation: none !important; }"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    base = os.environ.get("BENCH_BASE_URL")
    if not base:
        pytest.skip("BENCH_BASE_URL not set")
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, base_url=base)
    pg = ctx.new_page()
    pg.set_default_timeout(10_000)
    pg.goto("/")
    pg.add_style_tag(content=FREEZE_CSS)
    pg.wait_for_selector(".card")
    yield pg
    ctx.close()


def _card(page, title):
    return page.locator(".card", has_text=title).first


def test_overdue_card_has_class(page):
    for title in ("Set up CI pipeline", "Design landing page"):  # seeded overdue
        classes = _card(page, title).get_attribute("class")
        assert "card--overdue" in classes.split()


def test_overdue_card_left_border(page):
    card = _card(page, "Set up CI pipeline")
    style = card.evaluate(
        "el => { const s = getComputedStyle(el);"
        " return [s.borderLeftWidth, s.borderLeftStyle, s.borderLeftColor]; }"
    )
    assert style == ["3px", "solid", "rgb(220, 38, 38)"]


def test_overdue_badge_text(page):
    badge = _card(page, "Design landing page").locator(".overdue-badge")
    assert badge.count() == 1
    assert badge.text_content().strip() == "OVERDUE"


def test_non_overdue_card_unmarked(page):
    card = _card(page, "Write onboarding docs")  # due in 5 days
    assert "card--overdue" not in (card.get_attribute("class") or "").split()
    assert card.locator(".overdue-badge").count() == 0


def test_card_without_due_date_unmarked(page):
    form = page.locator(".new-card-form").first
    form.locator(".new-card-title").fill("Dateless card")
    form.locator(".new-card-submit").click()
    card = page.locator(".card", has_text="Dateless card").first
    card.wait_for()
    assert "card--overdue" not in (card.get_attribute("class") or "").split()
