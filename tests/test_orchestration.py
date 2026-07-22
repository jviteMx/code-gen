"""Tests for the multi-agent orchestration layer (fake clients, no network)."""

import json
import threading
import time
from pathlib import Path

from code_agent.coder.llm import Turn, OpenAIClient
from code_agent.coder.orchestration import (
    AgentSpec, run_agent, parallel, judge_panel, critic_review,
    parallel_investigate, extract_json, read_only_tools_for,
)


class FakeClient:
    """Scripted, thread-safe stand-in for an LLMClient."""
    name = "lmstudio"

    def __init__(self, turns=None, const=None, model="fake"):
        self.model = model
        self.temperature = 0.2
        self._turns = turns or []
        self._const = const
        self._i = 0
        self._lock = threading.Lock()

    def _next(self):
        if self._const is not None:
            return self._const
        with self._lock:
            t = self._turns[min(self._i, len(self._turns) - 1)]
            self._i += 1
            return t

    def complete(self, system, messages, tools):
        return self._next()

    def stream(self, system, messages, tools, on_text=None):
        t = self._next()
        if t.content and on_text:
            on_text(t.content)
        return t

    append_assistant = OpenAIClient.append_assistant
    append_tool_results = OpenAIClient.append_tool_results

    def for_model(self, model):
        return FakeClient(turns=self._turns, const=self._const, model=model)


def _tc(name, args):
    return {"id": f"c_{name}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


# ── parallel primitive ────────────────────────────────────────────────

def test_parallel_preserves_order_and_captures_errors():
    def ok(i):
        return lambda: i * 10

    def boom():
        raise ValueError("nope")

    results = parallel([ok(0), ok(1), boom, ok(3)], max_workers=4)
    assert results[0] == 0 and results[1] == 10 and results[3] == 30
    assert isinstance(results[2], ValueError)


def test_parallel_actually_concurrent():
    def slow():
        time.sleep(0.2)
        return 1
    start = time.time()
    parallel([slow, slow, slow, slow], max_workers=4)
    # 4 x 0.2s sequential would be 0.8s; concurrent should be well under.
    assert time.time() - start < 0.6


# ── run_agent ─────────────────────────────────────────────────────────

def test_run_agent_readonly_refuses_write(tmp_path):
    turns = [Turn(tool_calls=[_tc("write_file", {"path": "x.py", "content": "bad"})]),
             Turn(content="done")]
    client = FakeClient(turns=turns)
    spec = AgentSpec(name="a", client=client, system_prompt="s",
                     tools=read_only_tools_for(client), workdir=str(tmp_path), read_only=True)
    run_agent(spec, "task")
    assert not (tmp_path / "x.py").exists()  # write was refused, not executed


def test_run_agent_runs_readonly_tool_then_finishes(tmp_path):
    (tmp_path / "a.py").write_text("hello world\n")
    turns = [Turn(tool_calls=[_tc("read_file", {"path": "a.py"})]),
             Turn(content="I read the file: it says hello.")]
    client = FakeClient(turns=turns)
    spec = AgentSpec(name="a", client=client, system_prompt="s",
                     tools=read_only_tools_for(client), workdir=str(tmp_path))
    res = run_agent(spec, "read a.py")
    assert res.ok and "hello" in res.text


# ── extract_json ──────────────────────────────────────────────────────

def test_extract_json_from_prose():
    text = 'Here is my verdict.\n{"verdict": "approve", "issues": [], "summary": "ok"}\nThanks.'
    obj = extract_json(text)
    assert obj["verdict"] == "approve"


def test_extract_json_none_when_absent():
    assert extract_json("no json here") is None


# ── critic / judge / MoE ──────────────────────────────────────────────

def test_critic_review_structured():
    critic = AgentSpec(name="critic", client=FakeClient(
        const=Turn(content='{"verdict":"revise","issues":["off-by-one"],"summary":"close"}')),
        system_prompt="s", tools=[])
    res = critic_review("some diff", "diff", critic)
    assert res.structured["verdict"] == "revise"
    assert res.structured["issues"] == ["off-by-one"]


def test_judge_panel_picks_winner_and_synthesis():
    proposers = [
        AgentSpec(name="p0", client=FakeClient(const=Turn(content="Approach A: use a queue")),
                  system_prompt="s", tools=[]),
        AgentSpec(name="p1", client=FakeClient(const=Turn(content="Approach B: use a cache")),
                  system_prompt="s", tools=[]),
    ]
    judge = AgentSpec(name="judge", client=FakeClient(
        const=Turn(content='{"scores":[{"index":0,"score":6},{"index":1,"score":9}],"winner":1,"synthesis":"Use a cache, with a queue fallback."}')),
        system_prompt="s", tools=[])
    result = judge_panel("make it fast", proposers, judge, max_workers=2)
    assert result["winner_index"] == 1
    assert "cache" in result["synthesis"]


def test_judge_panel_single_proposal_skips_judge():
    proposers = [AgentSpec(name="p0", client=FakeClient(const=Turn(content="only plan")),
                           system_prompt="s", tools=[])]
    judge = AgentSpec(name="judge", client=FakeClient(const=Turn(content="{}")),
                      system_prompt="s", tools=[])
    result = judge_panel("task", proposers, judge)
    assert result["winner_index"] == 0 and result["synthesis"] == "only plan"


def test_parallel_investigate(tmp_path):
    def make_spec(st):
        return AgentSpec(name=f"e:{st}", client=FakeClient(const=Turn(content=f"findings for {st}")),
                         system_prompt="s", tools=[], workdir=str(tmp_path))
    results = parallel_investigate(["auth", "db", "routes"], make_spec, max_workers=3)
    assert len(results) == 3
    assert all(r.ok for r in results)
    assert results[1].text == "findings for db"
