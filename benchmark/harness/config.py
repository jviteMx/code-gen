"""Benchmark run configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]          # .../benchmark
TEMPLATE_DIR = BENCH_ROOT / "template_app"
TASKS_DIR = BENCH_ROOT / "tasks"
SUITES_DIR = BENCH_ROOT / "suites"
RESULTS_DIR = BENCH_ROOT / "results"

# Trials always run on a native (ext4) filesystem: /mnt/* is drastically slower
# under WSL2 and would dominate the wall-time numbers, and it keeps the agent's
# unrestricted run_command tool away from the repo checkout.
SCRATCH_ROOT = Path.home() / ".cache" / "code-agent-bench"


@dataclass
class BenchConfig:
    trials: int = 1
    levels: list[int] = field(default_factory=lambda: list(range(1, 8)))
    tasks: list[str] = field(default_factory=list)   # explicit task ids; empty = all in levels
    oracle: bool = False
    keep_workdirs: bool = False
    agent_bin: str = "code-agent"
    agent_args: list[str] = field(default_factory=list)  # extra code-agent flags (--supervise, …)
    timeout_scale: float = 1.0   # stretch task time budgets (slow models, orchestration)
    lmstudio_url: str = "http://localhost:1234"
    scratch_root: Path = SCRATCH_ROOT
    results_dir: Path = RESULTS_DIR
