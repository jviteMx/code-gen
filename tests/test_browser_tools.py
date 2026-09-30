"""Browser research tests; network requests stay on a local test page."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from code_agent.coder import browser_tools
from code_agent.coder.coding_tools import PLAN_TOOL_NAMES
from code_agent.coder.tool_executor import CodingToolExecutor


class SearchPage(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'''<!doctype html><html><head><title>Flights</title></head><body>
<label for="from">From</label><input id="from" />
<label for="to">To</label><input id="to" />
<button onclick="document.getElementById('result').textContent =
  document.getElementById('from').value + ' to ' +
  document.getElementById('to').value + ': CAD 321'">Search</button>
<p id="result"></p></body></html>'''
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def search_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), SearchPage)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_browser_tools_available_in_assistant_mode():
    assert {"browser_open", "browser_snapshot", "browser_fill", "browser_click", "browser_close"} <= set(PLAN_TOOL_NAMES)


def test_browser_blocks_private_destinations_and_form_posts(monkeypatch):
    session = browser_tools.BrowserSession()
    outcomes = []

    class Request:
        url = "http://127.0.0.1/private"
        method = "GET"

        def is_navigation_request(self):
            return True

    class Route:
        request = Request()

        def abort(self):
            outcomes.append("blocked")

        def continue_(self):
            outcomes.append("allowed")

    route = Route()
    session._guard_request(route)
    assert outcomes == ["blocked"]

    monkeypatch.setattr(browser_tools, "_validate_public_url", lambda url: url)
    route.request.url = "https://example.com/submit"
    route.request.method = "POST"
    session._guard_request(route)
    assert outcomes[-1] == "blocked"


def test_browser_form_flow_in_isolated_context(search_server, monkeypatch, tmp_path):
    pytest.importorskip("playwright.sync_api")
    monkeypatch.setattr(browser_tools, "_validate_public_url", lambda url: url)
    executor = CodingToolExecutor(str(tmp_path))
    try:
        opened = json.loads(executor.execute("browser_open", {"url": search_server}))
        if "error" in opened and "Chromium is missing" in opened["error"]:
            pytest.skip("Playwright Chromium is not installed")
        assert opened["title"] == "Flights", opened
        assert any(item.get("text") == "Search" for item in opened["controls"])
        assert "error" not in json.loads(executor.execute(
            "browser_fill", {"target": "From", "value": "Calgary"},
        ))
        assert "error" not in json.loads(executor.execute(
            "browser_fill", {"target": "To", "value": "Halifax"},
        ))
        result = json.loads(executor.execute("browser_click", {"target": "Search"}))
        assert "Calgary to Halifax: CAD 321" in result["text"], result
        assert json.loads(executor.execute("browser_close", {})) == {"closed": True}
    finally:
        executor.close()
