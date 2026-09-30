"""Unit tests for bounded public-internet tools (no real network calls)."""

import base64
import json
import sys
import types

import pytest

from code_agent.coder import web_tools


class FakeResponse:
    def __init__(
        self, *, body=b"", status=200, content_type="text/plain", url="https://example.com/",
        headers=None, json_data=None,
    ):
        self._body = body
        self.status_code = status
        self.headers = headers or {"Content-Type": content_type}
        self.url = url
        self.encoding = "utf-8"
        self._json_data = json_data
        self.closed = False

    def iter_content(self, chunk_size=16384):
        yield self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data

    def close(self):
        self.closed = True


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(
        web_tools.socket, "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )


def test_web_search_bounds_and_sanitizes_results(monkeypatch):
    class FakeDDGS:
        def __init__(self, timeout):
            assert timeout == 20

        def text(self, query, max_results):
            assert query == "today's date"
            assert max_results == 10
            return [
                {"title": "Calendar", "href": "https://example.com/date", "body": "Today"},
                {"title": "bad", "href": "javascript:alert(1)", "body": "ignore"},
            ]

    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=FakeDDGS))
    result = web_tools.web_search("  today's date  ", max_results=999)

    assert result["count"] == 1
    assert result["results"][0]["url"] == "https://example.com/date"
    assert "untrusted" in result["warning"].lower()


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "http://user:password@example.com/",
    "http://127.0.0.1/admin",
    "http://[::1]/admin",
])
def test_web_fetch_rejects_non_public_targets(url, monkeypatch):
    monkeypatch.setattr(
        web_tools.socket, "getaddrinfo",
        lambda host, *args, **kwargs: [(2, 1, 6, "", (host, 80))],
    )
    with pytest.raises(ValueError):
        web_tools.web_fetch(url)


def test_web_fetch_extracts_text_and_ignores_scripts(public_dns, monkeypatch):
    response = FakeResponse(
        body=b"<html><head><title>Example</title><script>steal()</script></head>"
             b"<body><h1>Hello</h1><p>Useful text</p></body></html>",
        content_type="text/html; charset=utf-8",
    )
    monkeypatch.setattr(web_tools.requests, "get", lambda *args, **kwargs: response)

    result = web_tools.web_fetch("https://example.com/", max_chars=2000)

    assert result["title"] == "Example"
    assert "Hello" in result["text"] and "Useful text" in result["text"]
    assert "steal" not in result["text"]
    assert response.closed


def test_web_fetch_revalidates_redirect_destination(public_dns, monkeypatch):
    monkeypatch.setattr(
        web_tools.socket, "getaddrinfo",
        lambda host, *args, **kwargs: [
            (2, 1, 6, "", ("127.0.0.1" if host == "127.0.0.1" else "93.184.216.34", 443))
        ],
    )
    redirect = FakeResponse(
        status=302, headers={"Location": "http://127.0.0.1/private"},
        url="https://example.com/start",
    )
    monkeypatch.setattr(web_tools.requests, "get", lambda *args, **kwargs: redirect)

    with pytest.raises(ValueError, match="blocked"):
        web_tools.web_fetch("https://example.com/start")
    assert redirect.closed


def test_github_read_lists_directory(public_dns, monkeypatch):
    payload = [{
        "name": "README.md", "path": "README.md", "type": "file", "size": 12,
        "html_url": "https://github.com/octo/demo/blob/main/README.md",
    }]
    response = FakeResponse(body=json.dumps(payload).encode(), content_type="application/json")
    monkeypatch.setattr(web_tools.requests, "get", lambda *args, **kwargs: response)

    result = web_tools.github_read("octo", "demo")

    assert result["type"] == "directory"
    assert result["entries"][0]["path"] == "README.md"


def test_github_read_decodes_file(public_dns, monkeypatch):
    payload = {
        "type": "file", "encoding": "base64",
        "content": base64.b64encode(b"# Hello\n").decode(),
        "size": 8, "html_url": "https://github.com/octo/demo/blob/main/README.md",
    }
    response = FakeResponse(body=json.dumps(payload).encode(), content_type="application/json")
    monkeypatch.setattr(web_tools.requests, "get", lambda *args, **kwargs: response)

    result = web_tools.github_read("octo", "demo", "README.md", ref="main")

    assert result["text"] == "# Hello\n"
    assert result["type"] == "file"


def test_github_read_rejects_path_traversal():
    with pytest.raises(ValueError, match="traversal"):
        web_tools.github_read("octo", "demo", "../secret")


def test_github_read_caps_json_response(public_dns, monkeypatch):
    response = FakeResponse(body=b"x" * (web_tools._MAX_DOWNLOAD_BYTES + 1))
    monkeypatch.setattr(web_tools.requests, "get", lambda *args, **kwargs: response)

    with pytest.raises(ValueError, match="download limit"):
        web_tools.github_read("octo", "demo")
