"""Frontend P2P smoke suite: the built app must render and stay interactive.

Runs against a served trial via BENCH_BASE_URL. Self-contained (module-level
Playwright fixture) so it works no matter where pytest is invoked from.
"""

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
    pg.wait_for_selector(".column")
    yield pg
    ctx.close()


def test_board_renders_three_columns(page):
    assert page.locator(".column").count() == 3


def test_seeded_cards_visible(page):
    assert page.locator(".card").count() >= 8
    assert page.get_by_text("Fix login redirect bug").count() >= 1


def test_column_titles_present(page):
    titles = page.locator(".column-title").all_text_contents()
    assert "To Do" in titles and "In Progress" in titles and "Done" in titles


def test_create_card_updates_dom(page):
    first_form = page.locator(".new-card-form").first
    before = page.locator(".card").count()
    first_form.locator(".new-card-title").fill("Smoke test card")
    first_form.locator(".new-card-submit").click()
    page.wait_for_function(
        f"document.querySelectorAll('.card').length === {before + 1}"
    )
    assert page.get_by_text("Smoke test card").count() >= 1
