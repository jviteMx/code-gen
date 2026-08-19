"""Tests for the /benchmark slash command (no subprocess actually spawned)."""

from code_agent.coder.llm import Turn
from code_agent.coder.session import CoderSession
from code_agent.coder.session_memory import SessionMemory
from code_agent.coder.token_counter import TokenTracker
from code_agent.coder.tool_executor import CodingToolExecutor
from code_agent.coder.ui import ReplUI, SLASH_COMMANDS

from test_orchestration import FakeClient
from test_session_orchestration import FakeClaude


def _session(tmp_path, client, **kw):
    return CoderSession(
        client=client, ui=ReplUI(str(tmp_path)),
        executor=CodingToolExecutor(str(tmp_path)),
        memory=SessionMemory(str(tmp_path)), tracker=TokenTracker(8192),
        workdir=str(tmp_path), plan_mode=False, **kw,
    )


class FakePopen:
    calls: list = []

    def __init__(self, cmd, **kw):
        self.cmd = cmd
        self.kw = kw
        self.stdout = iter(["[1/18] L1-01 trial 0 … RESOLVED\n"])
        self.returncode = 0
        FakePopen.calls.append(self)

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        pass


def test_benchmark_command_registered(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x")))
    assert "/benchmark" in s._commands
    assert "/bench" in s._commands
    assert "/benchmark" in SLASH_COMMANDS


def test_benchmark_spawns_runner_with_pinned_model(tmp_path, monkeypatch):
    import subprocess
    FakePopen.calls = []
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    s = _session(tmp_path, FakeClient(const=Turn(content="x"), model="qwen3.5-9b"))
    s._cmd_benchmark("--levels 1 --trials 2")
    assert len(FakePopen.calls) == 1
    call = FakePopen.calls[0]
    assert call.cmd[1:3] == ["-m", "benchmark.harness.run"]
    assert "--levels" in call.cmd and "--trials" in call.cmd
    assert "--lmstudio-url" in call.cmd
    env = call.kw["env"]
    assert env["LMSTUDIO_MODEL"] == "qwen3.5-9b"
    assert env["AI_PROVIDER"] == "lmstudio"


def test_benchmark_oracle_shorthand(tmp_path, monkeypatch):
    import subprocess
    FakePopen.calls = []
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    s = _session(tmp_path, FakeClient(const=Turn(content="x")))
    s._cmd_benchmark("oracle")
    assert "--oracle" in FakePopen.calls[0].cmd
    assert "LMSTUDIO_MODEL" not in FakePopen.calls[0].kw["env"]


def test_benchmark_refuses_claude_main(tmp_path, monkeypatch):
    import subprocess
    FakePopen.calls = []
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    s = _session(tmp_path, FakeClaude(const=Turn(content="x")))
    s._cmd_benchmark("")
    assert FakePopen.calls == []  # warned instead of spawning


def test_benchmark_oracle_allowed_with_claude_main(tmp_path, monkeypatch):
    import subprocess
    FakePopen.calls = []
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    s = _session(tmp_path, FakeClaude(const=Turn(content="x")))
    s._cmd_benchmark("--oracle")
    assert len(FakePopen.calls) == 1
