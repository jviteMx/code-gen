"""Playwright F2P: pill-styled live card-count chips in column headers."""

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


def test_every_column_has_chip_in_header(page):
    assert page.locator(".column-header .count-chip").count() == 3


def test_chip_counts_match_seeded_cards(page):
    chips = page.locator(".count-chip").all_text_contents()
    assert [c.strip() for c in chips] == ["4", "2", "2"]


def test_chip_is_pill_styled(page):
    chip = page.locator(".count-chip").first
    radius, chip_bg = chip.evaluate(
        "el => { const s = getComputedStyle(el);"
        " return [parseFloat(s.borderTopLeftRadius), s.backgroundColor]; }"
    )
    column_bg = page.locator(".column").first.evaluate(
        "el => getComputedStyle(el).backgroundColor")
    assert radius >= 8
    assert chip_bg not in (column_bg, "rgba(0, 0, 0, 0)")


def test_chip_text_smaller_than_title(page):
    chip_size = page.locator(".count-chip").first.evaluate(
        "el => parseFloat(getComputedStyle(el).fontSize)")
    title_size = page.locator(".column-title").first.evaluate(
        "el => parseFloat(getComputedStyle(el).fontSize)")
    assert chip_size < title_size


def test_chip_updates_after_adding_card(page):
    first_column = page.locator(".column").first
    form = first_column.locator(".new-card-form")
    form.locator(".new-card-title").fill("Chip counter test")
    form.locator(".new-card-submit").click()
    page.wait_for_function(
        "document.querySelector('.column .count-chip')?.textContent.trim() === '5'"
    )
