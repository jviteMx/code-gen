"""Session-level approval and assistant-mode boundaries for public research."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

from test_orchestration import FakeClient

from code_agent.coder.llm import Turn
from code_agent.coder.session import CoderSession
from code_agent.coder.session_memory import SessionMemory
from code_agent.coder.token_counter import TokenTracker
from code_agent.coder.tool_executor import CodingToolExecutor
from code_agent.coder.ui import ReplUI


def session(tmp_path):
    return CoderSession(
        client=FakeClient(const=Turn(content="done")), ui=ReplUI(str(tmp_path)),
        executor=CodingToolExecutor(str(tmp_path)), memory=SessionMemory(str(tmp_path)),
        tracker=TokenTracker(8192), workdir=str(tmp_path), initial_mode="assistant",
        stream=False,
    )


def call(s, name, args):
    messages = []
    s._execute_tools([{
        "id": name, "function": {"name": name, "arguments": json.dumps(args)},
    }], messages)
    return json.loads(messages[-1]["content"])


def test_one_approval_covers_search_pages_github_and_browser(tmp_path, monkeypatch):
    s = session(tmp_path)
    prompts = []
    monkeypatch.setattr("builtins.input", lambda question: prompts.append(question) or "yes")
    executed = []
    monkeypatch.setattr(s.executor, "execute", lambda name, args: executed.append(name) or '{}')
    for name, args in [
        ("web_search", {"query": "news"}),
        ("web_fetch", {"url": "https://example.com/"}),
        ("github_read", {"owner": "psf", "repo": "requests"}),
        ("browser_open", {"url": "https://example.com/"}),
        ("browser_snapshot", {}),
    ]:
        assert call(s, name, args) == {}
    assert len(prompts) == 1
    assert executed == ["web_search", "web_fetch", "github_read", "browser_open", "browser_snapshot"]
    s._cmd_web("off")
    assert "denied" in call(s, "browser_click", {"target": "Search"})["error"]
    assert call(s, "browser_close", {}) == {}
    s._cmd_web("ask")
    assert call(s, "web_search", {"query": "again"}) == {}
    assert len(prompts) == 2


def test_assistant_mode_rejects_write_tools(tmp_path, monkeypatch):
    s = session(tmp_path)
    monkeypatch.setattr(s.executor, "execute", lambda *args: (_ for _ in ()).throw(AssertionError("executed")))
    result = call(s, "write_file", {"path": "bad.txt", "content": "bad"})
    assert "unavailable" in result["error"]
    assert not (tmp_path / "bad.txt").exists()


def test_concurrent_web_requests_share_one_prompt(tmp_path, monkeypatch):
    s = session(tmp_path)
    prompts = []
    lock = threading.Lock()

    def answer(question):
        with lock:
            prompts.append(question)
        return "y"

    monkeypatch.setattr("builtins.input", answer)
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert list(pool.map(s._authorize_web, ["request"] * 6)) == [True] * 6
    assert len(prompts) == 1
