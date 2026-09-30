"""Isolated public-web browser for sites that require JavaScript and forms.

Playwright objects live on one dedicated executor thread. Each agent session gets
an ephemeral browser context with no access to the user's regular browser data.
"""

from __future__ import annotations

import os
from urllib.parse import urljoin

from code_agent.coder.web_tools import _WARNING, _validate_public_url

_MAX_TEXT = 20_000
_MAX_ELEMENTS = 60
_MAX_REQUESTS = 300


class BrowserSession:
    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._request_count = 0

    def _start(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                'Browser support is missing. Install with pip install -e ".[browser]" '
                'and run playwright install chromium.'
            ) from exc
        self._playwright = sync_playwright().start()
        try:
            headed = os.environ.get("CODE_AGENT_BROWSER_HEADED", "").lower() in {
                "1", "true", "yes", "on",
            }
            self._browser = self._playwright.chromium.launch(headless=not headed)
            self._context = self._browser.new_context(
                accept_downloads=False, service_workers="block", permissions=[],
            )
            self._context.route("**/*", self._guard_request)
            if hasattr(self._context, "route_web_socket"):
                self._context.route_web_socket("**/*", lambda socket: socket.close())
            self._page = self._context.new_page()
            self._page.set_default_timeout(10_000)
        except Exception as exc:
            self.close()
            if "Executable doesn't exist" in str(exc):
                raise RuntimeError(
                    "Chromium is missing. Run playwright install chromium."
                ) from exc
            raise

    def _guard_request(self, route) -> None:
        self._request_count += 1
        request = route.request
        try:
            if self._request_count > _MAX_REQUESTS:
                raise ValueError("Browser request limit exceeded")
            _validate_public_url(request.url)
            # Search sites often use POST for API queries, but a form POST that
            # navigates the page may create an account, order, or other record.
            if request.is_navigation_request() and request.method != "GET":
                raise ValueError("Browser form submissions are disabled")
            if request.method not in {"GET", "POST"}:
                raise ValueError("Browser write requests are disabled")
        except ValueError:
            route.abort()
        else:
            route.continue_()

    def open(self, url: str) -> dict:
        _validate_public_url(url)
        self._start()
        self._request_count = 0
        self._page.goto(url, wait_until="domcontentloaded", timeout=25_000)
        return self.snapshot()

    def snapshot(self, max_chars: int = 12_000) -> dict:
        if self._page is None:
            raise ValueError("No browser page is open. Call browser_open first.")
        limit = max(1000, min(int(max_chars), _MAX_TEXT))
        page = self._page
        url = page.url
        if url != "about:blank":
            _validate_public_url(url)
        body = page.locator("body")
        text = body.inner_text(timeout=5_000) if body.count() else ""
        controls = []
        for element in page.locator("input, textarea, select, button, a").all()[:_MAX_ELEMENTS]:
            try:
                if not element.is_visible():
                    continue
                tag = element.evaluate("el => el.tagName.toLowerCase()")
                item = {"tag": tag}
                for attr in ("id", "name", "type", "aria-label", "placeholder", "href"):
                    value = element.get_attribute(attr)
                    if value:
                        item[attr] = value[:180]
                label = element.inner_text(timeout=1_000).strip()[:160]
                if label:
                    item["text"] = label
                controls.append(item)
            except Exception:  # noqa: BLE001 - a dynamic page may replace elements
                continue
        return {
            "url": url,
            "title": page.title()[:300],
            "text": text[:limit],
            "truncated": len(text) > limit,
            "controls": controls,
            "warning": _WARNING,
        }

    def _target(self, target: str, by: str, *, role: str = "button"):
        if self._page is None:
            raise ValueError("No browser page is open. Call browser_open first.")
        if not target or len(target) > 300:
            raise ValueError("Browser target is missing or too long")
        if by == "label":
            return self._page.get_by_label(target, exact=True)
        if by == "placeholder":
            return self._page.get_by_placeholder(target, exact=True)
        if by == "role":
            if role not in {"button", "link", "textbox", "combobox"}:
                raise ValueError("Unsupported browser role")
            return self._page.get_by_role(role, name=target, exact=True)
        if by == "text":
            return self._page.get_by_text(target, exact=True)
        if by == "css":
            return self._page.locator(target)
        raise ValueError("Use label, placeholder, role, text, or css targeting")

    def fill(self, target: str, value: str, by: str = "label") -> dict:
        if len(value) > 500:
            raise ValueError("Browser input is limited to 500 characters")
        locator = self._target(target, by, role="textbox")
        locator.fill(value, timeout=10_000)
        return self.snapshot()

    def click(self, target: str, by: str = "role", role: str = "button") -> dict:
        locator = self._target(target, by, role=role)
        href = locator.get_attribute("href", timeout=5_000)
        if href:
            _validate_public_url(urljoin(self._page.url, href))
        locator.click(timeout=10_000)
        try:
            self._page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except Exception:  # noqa: BLE001 - AJAX updates may have no navigation
            pass
        return self.snapshot()

    def close(self) -> dict:
        for obj in (self._context, self._browser, self._playwright):
            if obj is not None:
                try:
                    obj.stop() if obj is self._playwright else obj.close()
                except Exception:  # noqa: BLE001 - continue cleanup after browser failure
                    pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        return {"closed": True}
