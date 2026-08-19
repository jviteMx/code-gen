"""Playwright F2P: delete button removes a card; restore brings it back."""

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
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, base_url=base)
    pg = ctx.new_page()
    pg.set_default_timeout(10_000)
    pg.goto("/")
    pg.add_style_tag(content=FREEZE_CSS)
    pg.wait_for_selector(".card")
    yield pg
    ctx.close()


def test_cards_have_delete_buttons(page):
    assert page.locator(".card .card-delete").count() >= 8


def test_recently_deleted_section_exists(page):
    assert page.locator(".recently-deleted").count() == 1


def test_delete_moves_card_to_recently_deleted(page):
    card = page.locator(".card", has_text="Configure linters").first
    card.locator(".card-delete").click()
    page.wait_for_function(
        "!Array.from(document.querySelectorAll('.card')).some("
        "  el => el.textContent.includes('Configure linters'))"
    )
    section = page.locator(".recently-deleted")
    assert "Configure linters" in section.text_content()


def test_restore_brings_card_back_to_board(page):
    title = "Bootstrap project skeleton"
    card = page.locator(".card", has_text=title).first
    card.locator(".card-delete").click()
    section = page.locator(".recently-deleted")
    section.get_by_text(title).wait_for()

    def on_board():
        return page.locator(".card", has_text=title).count() > 0

    # restore entries until the target card is back (earlier tests may have
    # left other cards in the recently-deleted list)
    for _ in range(6):
        if on_board():
            break
        section.locator(".restore-btn").first.click()
        page.wait_for_timeout(300)
    assert on_board()
    assert title not in section.text_content()
