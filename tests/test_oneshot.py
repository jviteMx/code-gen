"""Tests for the --oneshot headless mode (fake clients, no network)."""

import json
import sys

import pytest

from code_agent.coder.llm import Turn
from code_agent.coder.session import CoderSession
from code_agent.coder.session_memory import SessionMemory
from code_agent.coder.token_counter import TokenTracker
from code_agent.coder.tool_executor import CodingToolExecutor
from code_agent.coder.ui import ReplUI

from test_orchestration import FakeClient


def _session(tmp_path, client, plan_mode=False, **kw):
    return CoderSession(
        client=client, ui=ReplUI(str(tmp_path)),
        executor=CodingToolExecutor(str(tmp_path)),
        memory=SessionMemory(str(tmp_path)), tracker=TokenTracker(8192),
        workdir=str(tmp_path), plan_mode=plan_mode, **kw,
    )


def test_oneshot_direct_runs_and_returns(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="all done")))
    assert s.mode == "direct"
    s.run_oneshot("add a hello function")
    assert any(m["role"] == "user" and "hello function" in m["content"]
               for m in s.messages)


def test_oneshot_plan_auto_approves_and_executes(tmp_path):
    plan = Turn(content="1. do the thing\n\nReady to execute.")
    done = Turn(content="executed")
    s = _session(tmp_path, FakeClient(turns=[plan, done]), plan_mode=True,
                 auto_approve=True)
    assert s.mode == "plan"
    s.run_oneshot("build the feature")
    # _handle_plan captured the plan, auto-approval chained into execution
    # and _handle_approval leaves the session in direct mode afterwards.
    assert s.mode == "direct"
    assert s.current_plan is None


def test_oneshot_auto_panel_plan_auto_executes(tmp_path, monkeypatch):
    plan = "1. do the thing\n\nReady to execute."
    s = _session(tmp_path, FakeClient(const=Turn(content="executed")), auto_approve=True)

    def fake_suggest(prompt):
        s.current_plan = plan
        s.mode = "approve"
        return True

    monkeypatch.setattr(s, "_maybe_suggest", fake_suggest)
    s.run_oneshot("build the feature")
    assert s.mode == "direct"       # approval chained into execution
    assert s.current_plan is None


def test_oneshot_auto_investigate_still_implements(tmp_path, monkeypatch):
    s = _session(tmp_path, FakeClient(const=Turn(content="done")))

    def fake_suggest(prompt):
        s.messages.append({"role": "user",
                           "content": "[Parallel investigation findings]\n\nfindings here"})
        return True

    monkeypatch.setattr(s, "_maybe_suggest", fake_suggest)
    s.run_oneshot("implement the widget")
    contents = [str(m.get("content", "")) for m in s.messages]
    assert any("investigation findings" in c for c in contents)
    assert any("implement the widget" in c for c in contents)  # task still dispatched


def test_oneshot_missing_claude_key_exits_nonzero(tmp_path, monkeypatch):
    from code_agent.coder.loop import run_coding_session
    with pytest.raises(SystemExit) as exc:
        run_coding_session(
            workdir=str(tmp_path), context="task", provider="claude",
            anthropic_api_key=None, preflight=False, oneshot=True,
        )
    assert exc.value.code == 1


def test_oneshot_writes_stats_file(tmp_path):
    from code_agent.coder.loop import _write_oneshot_stats
    memory = SessionMemory(str(tmp_path))
    tracker = TokenTracker(8192)
    tracker.total_requests = 7
    _write_oneshot_stats(str(tmp_path), tracker, "lmstudio", "qwen-test", memory)
    stats = json.loads((tmp_path / ".jt" / "oneshot_stats.json").read_text())
    assert stats["total_requests"] == 7
    assert stats["model"] == "qwen-test"
    assert stats["provider"] == "lmstudio"


def test_cli_oneshot_requires_prompt(monkeypatch, tmp_path):
    from code_agent import cli
    monkeypatch.setattr(sys, "argv", ["code-agent", str(tmp_path), "--oneshot"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_cli_plan_flag_overrides_no_plan(monkeypatch, tmp_path):
    import code_agent.coder.loop as loop_mod
    import code_agent.config as config_mod
    from code_agent import cli
    captured = {}
    monkeypatch.setattr(loop_mod, "run_coding_session", lambda **kw: captured.update(kw))
    monkeypatch.setattr(config_mod, "load_config",
                        lambda **kw: config_mod.Config(ai_provider="lmstudio"))
    monkeypatch.setattr(sys, "argv",
                        ["code-agent", str(tmp_path), "--no-plan", "--plan"])
    cli.main()
    assert captured["plan_mode"] is True

    captured.clear()
    monkeypatch.setattr(sys, "argv", ["code-agent", str(tmp_path), "--no-plan"])
    cli.main()
    assert captured["plan_mode"] is False
