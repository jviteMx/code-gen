"""Playwright F2P: columns stack vertically below 700px, row layout above."""

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


def _page(browser, width, height=900):
    base = os.environ.get("BENCH_BASE_URL")
    if not base:
        pytest.skip("BENCH_BASE_URL not set")
    ctx = browser.new_context(viewport={"width": width, "height": height}, base_url=base)
    pg = ctx.new_page()
    pg.set_default_timeout(10_000)
    pg.goto("/")
    pg.add_style_tag(content=FREEZE_CSS)
    pg.wait_for_selector(".card")
    return ctx, pg


def _column_boxes(page):
    boxes = []
    for i in range(page.locator(".column").count()):
        boxes.append(page.locator(".column").nth(i).bounding_box())
    return boxes


def test_narrow_viewport_stacks_columns(browser):
    ctx, page = _page(browser, 500)
    try:
        boxes = _column_boxes(page)
        assert len(boxes) == 3
        xs = [round(b["x"]) for b in boxes]
        ys = [b["y"] for b in boxes]
        assert len(set(xs)) == 1, f"columns not left-aligned when stacked: {xs}"
        assert ys == sorted(ys) and len(set(ys)) == 3, "columns must stack vertically"
    finally:
        ctx.close()


def test_narrow_columns_full_width(browser):
    ctx, page = _page(browser, 500)
    try:
        for box in _column_boxes(page):
            assert box["width"] > 400, f"column too narrow when stacked: {box['width']}"
    finally:
        ctx.close()


def test_narrow_viewport_no_horizontal_scroll(browser):
    ctx, page = _page(browser, 500)
    try:
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 0
    finally:
        ctx.close()


def test_wide_viewport_keeps_row_layout(browser):
    ctx, page = _page(browser, 1280)
    try:
        boxes = _column_boxes(page)
        ys = {round(b["y"]) for b in boxes}
        xs = [b["x"] for b in boxes]
        assert len(ys) == 1, "columns must share a row on wide screens"
        assert xs == sorted(xs) and len(set(xs)) == 3
        assert all(abs(b["width"] - 280) < 2 for b in boxes)
    finally:
        ctx.close()
