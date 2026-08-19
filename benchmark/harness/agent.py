"""Invoking code-agent headlessly against a trial workspace."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .procutil import kill_tree, popen_group_kwargs
from .schemas import TaskSpec


@dataclass
class AgentRun:
    wall_s: float
    exit_code: int | None
    timeout: bool
    stats: dict = field(default_factory=dict)


def build_cmd(task: TaskSpec, agent_bin: str, extra_args: list[str] | None = None) -> list[str]:
    """The code-agent invocation for one trial. extra_args go last, so flags like
    --max-parallel or --timeout can be overridden by an orchestrated config."""
    return [
        agent_bin, ".",
        "--oneshot", "--prompt", task.prompt,
        "--yes", "--no-plan", "--no-preflight", "--no-stream",
        "--timeout", str(task.request_timeout_s),
        "--max-parallel", "1",
        *(extra_args or []),
    ]


def run_agent(trial_dir: Path, task: TaskSpec, agent_bin: str, log_path: Path,
              lmstudio_url: str | None = None,
              extra_args: list[str] | None = None) -> AgentRun:
    cmd = build_cmd(task, agent_bin, extra_args)
    start = time.monotonic()
    timed_out = False
    with open(log_path, "w", encoding="utf-8") as log:
        # AI_PROVIDER pinned so a claude-flavored user config can't hijack the run;
        # LMSTUDIO_MODEL (if set by the caller) rides along via os.environ.
        # PYTHONUTF8/PYTHONIOENCODING: with stdout redirected to agent.log, Windows
        # Python defaults to cp1252 and rich's banner characters crash the agent.
        env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb", "AI_PROVIDER": "lmstudio",
               "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        if lmstudio_url:
            env["LMSTUDIO_URL"] = lmstudio_url
        proc = subprocess.Popen(cmd, cwd=trial_dir, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env, **popen_group_kwargs())
        try:
            proc.wait(timeout=task.timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_tree(proc)
    wall = time.monotonic() - start

    stats = {}
    stats_file = trial_dir / ".jt" / "oneshot_stats.json"
    if stats_file.exists():
        try:
            stats = json.loads(stats_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return AgentRun(wall_s=round(wall, 1), exit_code=proc.returncode,
                    timeout=timed_out, stats=stats)


def tail_failure_hint(log_path: Path) -> str | None:
    """Classify obvious failure modes from the end of the agent log."""
    try:
        tail = log_path.read_text(errors="replace")[-4000:].lower()
    except OSError:
        return None
    if "context is" in tail and "full" in tail:
        return "context-exhausted"
    if "[error]" in tail and "api" in tail:
        return "api-error"
    if "repeating the same tool call" in tail or "stuck" in tail:
        return "stalled"
    return None
