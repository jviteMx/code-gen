"""Benchmark runner.

    python -m benchmark.harness.run --levels 1-7 --trials 3
    python -m benchmark.harness.run --oracle            # validate tasks, no model
    python -m benchmark.harness.run --tasks L1-01,L4-02

Run from the code-agent directory. Results land in benchmark/results/<run_id>/.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_MISSING = [m for m in ("yaml", "fastapi", "uvicorn", "httpx", "playwright", "schemathesis")
            if importlib.util.find_spec(m) is None]
if _MISSING:
    sys.exit(
        f"benchmark dependencies missing in this Python environment: {', '.join(_MISSING)}\n"
        "Install them with:\n"
        "    pip install -e \".[bench]\"\n"
        "    playwright install chromium"
    )

from . import grade as grader  # noqa: E402
from . import metrics, report, workspace  # noqa: E402
from .agent import run_agent, tail_failure_hint  # noqa: E402
from .config import BenchConfig, TASKS_DIR  # noqa: E402
from .schema_check import run_schemathesis  # noqa: E402
from .schemas import TaskSpec, TrialResult  # noqa: E402


def effective_max_parallel(agent_args: list[str]) -> int:
    """Return code-agent's effective worker cap (last CLI occurrence wins)."""
    value = 1  # benchmark agent.py's conservative default
    for i, arg in enumerate(agent_args):
        raw = None
        if arg == "--max-parallel" and i + 1 < len(agent_args):
            raw = agent_args[i + 1]
        elif arg.startswith("--max-parallel="):
            raw = arg.split("=", 1)[1]
        if raw is not None:
            try:
                value = max(1, int(raw))
            except ValueError:
                pass
    return value


def discover_tasks(cfg: BenchConfig) -> list[TaskSpec]:
    specs = [TaskSpec.load(p.parent) for p in sorted(TASKS_DIR.glob("L*/*/task.yaml"))]
    if cfg.tasks:
        wanted = set(cfg.tasks)
        specs = [s for s in specs if s.id in wanted]
        missing = wanted - {s.id for s in specs}
        if missing:
            sys.exit(f"unknown task ids: {', '.join(sorted(missing))}")
    else:
        specs = [s for s in specs if s.level in cfg.levels]
    if not specs:
        sys.exit("no tasks selected")
    return specs


def preflight(cfg: BenchConfig, needs_node: bool, needs_browser: bool) -> dict:
    meta: dict = {"oracle": cfg.oracle, "trials_per_task": cfg.trials, "model": None,
                  "agent_args": cfg.agent_args, "timeout_scale": cfg.timeout_scale,
                  "routing_policy_version": "auto-v2" if "--auto" in cfg.agent_args else None,
                  "effective_max_parallel": effective_max_parallel(cfg.agent_args)}
    if "--auto" in cfg.agent_args and meta["effective_max_parallel"] <= 1:
        print("WARNING: --auto is enabled but effective --max-parallel is 1. "
              "The router can select investigate/panel, but those routes cannot execute "
              "in parallel; add --max-parallel 3 for the intended comparison.")
    if not cfg.oracle:
        if shutil.which(cfg.agent_bin) is None:
            sys.exit(f"'{cfg.agent_bin}' not found in PATH — pip install -e . first")
        from code_agent.lmstudio import LMStudioManager
        mgr = LMStudioManager(cfg.lmstudio_url)
        if not mgr.is_available():
            sys.exit(f"LM Studio not reachable at {cfg.lmstudio_url} — start it "
                     "(with the server enabled) and load a model first.")
        # honor a pinned model (e.g. set by code-agent's /benchmark command),
        # otherwise take whatever is loaded
        model = None
        pinned = os.environ.get("LMSTUDIO_MODEL", "")
        if pinned and pinned != "default":
            model = next((m for m in mgr.list_models() if m.get("key") == pinned), None)
            if model is None:
                sys.exit(f"pinned model '{pinned}' not found in LM Studio")
        if model is None:
            model = mgr.get_loaded_model()
        if model is None or model.get("type") == "embedding":
            sys.exit("no chat model loaded in LM Studio")
        meta["model"] = model
        # LMStudio's JIT default context is 4096 — the agent's system prompt and
        # tools nearly fill that, so trial results would be meaningless.
        ctx = model.get("loaded_context_length")
        meta["loaded_context_length"] = ctx
        if ctx and ctx < 8192:
            sys.exit(f"{model.get('key')} is loaded with only {ctx:,} tokens of context — "
                     "results would be meaningless. Reload it with 16384+ (LM Studio "
                     "per-model settings, or /model N in code-agent, which requests 32k).")
        if ctx is None:
            print("NOTE: couldn't detect the model's effective context. LM Studio's API "
                  "default is 4096, which is far too small — make sure the model is "
                  "loaded with 16384+ (check the load settings in LM Studio).")
        # Record everything resident: a second loaded model competes for VRAM
        # and silently skews wall times, so confounded runs must be visible.
        loaded = [m for m in mgr.list_models() if m.get("loaded")]
        meta["loaded_models"] = [m.get("key") for m in loaded]
        extra_chat = [m["key"] for m in loaded
                      if m.get("type") != "embedding" and m.get("key") != model.get("key")]
        if extra_chat:
            print(f"WARNING: other chat models are loaded alongside {model.get('key')}: "
                  f"{', '.join(extra_chat)}. VRAM contention will inflate wall times and "
                  "can flip trials to timeout — unload them for a clean run "
                  "(in code-agent: /model N on that model toggles it unloaded).")
    if needs_node and shutil.which("npm") is None:
        sys.exit("npm not found — Node >= 20 is required for frontend tasks")
    if needs_browser:
        from playwright.sync_api import sync_playwright

        def _chromium_launches() -> Exception | None:
            try:
                with sync_playwright() as p:
                    p.chromium.launch().close()
                return None
            except Exception as e:  # noqa: BLE001 — any launch failure means "not usable"
                return e

        err = _chromium_launches()
        if err is not None:
            # The browser binary is a user-level, idempotent download — fetch it
            # instead of bouncing the run (pip can't do this step for us).
            print("Playwright chromium not available — downloading it now (one-time, ~120 MB)…")
            r = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])
            err = _chromium_launches() if r.returncode == 0 else err
            if err is not None:
                reason = str(err).splitlines()[0] if str(err) else type(err).__name__
                sys.exit(f"Playwright chromium still unavailable ({reason})\n"
                         "On Linux/WSL the system libraries may be missing — run: "
                         "sudo playwright install-deps chromium")
    try:
        meta["code_agent_sha"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        meta["code_agent_sha"] = None
    return meta


def run_trial(task: TaskSpec, trial_no: int, cfg: BenchConfig, run_scratch: Path,
              out_root: Path, node_modules: Path | None) -> TrialResult:
    name = f"{task.id}-t{trial_no}"
    out_dir = out_root / "trials" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    result = TrialResult(task_id=task.id, level=task.level, trial=trial_no)

    trial = workspace.make_trial_dir(run_scratch, name,
                                     node_modules if task.frontend else None)
    try:
        baseline = workspace.git_baseline(trial)

        if cfg.oracle:
            workspace.apply_patch(trial, task.dir / "reference.patch")
            result.wall_s = 0.0
        else:
            run = run_agent(trial, task, cfg.agent_bin, out_dir / "agent.log",
                            lmstudio_url=cfg.lmstudio_url, extra_args=cfg.agent_args)
            result.wall_s = run.wall_s
            result.exit_code = run.exit_code
            result.timeout = run.timeout
            result.requests = run.stats.get("total_requests")
            result.tokens_used = run.stats.get("used_tokens")
            result.routing = dict(run.stats.get("routing") or {})
            if run.timeout:
                result.failure = "wall-timeout"
            elif run.exit_code not in (0, None) and not run.stats:
                # the agent died before finishing a single task turn — a setup
                # problem, not a model result; see agent.log for the traceback
                result.failure = f"agent-crashed (exit {run.exit_code})"
            else:
                result.failure = tail_failure_hint(out_dir / "agent.log")

        workspace.snapshot(trial)
        (out_dir / "diff.patch").write_text(
            workspace.diff_patch(trial, baseline), encoding="utf-8"
        )
        numstat = workspace.diff_numstat(trial, baseline)
        result.files_changed = len(numstat)
        result.loc_changed = sum(a + r for a, r, _ in numstat)

        sub, resolved, tampered, detail = grader.grade(
            trial, task, baseline, out_dir, schemathesis_runner=run_schemathesis)
        result.subscores = sub
        result.resolved = resolved
        result.p2p_tampered = tampered
        result.score = grader.score(sub, task)
        result.detail = detail
        if not resolved and result.failure is None:
            if detail.get("gate", {}).get("backend_compile") is False:
                result.failure = "gate-fail"
            elif sub.f2p < 1.0:
                result.failure = "f2p-fail"
            elif sub.p2p < 1.0:
                result.failure = "p2p-regression"
    except Exception as e:  # a broken trial is a data point, not a crash
        result.error = f"{type(e).__name__}: {e}"
        result.failure = result.failure or "harness-error"
    finally:
        (out_dir / "grade.json").write_text(
            json.dumps(result.to_dict(), indent=2), encoding="utf-8"
        )
        if not cfg.keep_workdirs:
            shutil.rmtree(trial, ignore_errors=True)
    return result


def parse_levels(spec: str) -> list[int]:
    out: set[int] = set()
    for part in spec.split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(part))
    return sorted(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the code-agent coding benchmark.")
    ap.add_argument("--levels", default="1-7", help="e.g. 1-3 or 1,4,6 (default: all)")
    ap.add_argument("--tasks", default="", help="comma-separated task ids (overrides --levels)")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--oracle", action="store_true",
                    help="apply reference patches instead of running the agent")
    ap.add_argument("--keep-workdirs", action="store_true")
    ap.add_argument("--agent-bin", default="code-agent")
    ap.add_argument("--agent-args", default="",
                    help="extra code-agent flags per trial, quoted (e.g. "
                         "--agent-args \"--supervise --critic-model KEY\"). Scores an "
                         "orchestrated configuration instead of the bare loop; recorded "
                         "in the run metadata.")
    ap.add_argument("--timeout-scale", type=float, default=1.0,
                    help="multiply every task's wall/request timeouts (e.g. 3 for "
                         "CPU-offloaded big models or orchestrated runs). Recorded in "
                         "the run metadata; timings across different scales aren't "
                         "comparable but scores are.")
    ap.add_argument("--lmstudio-url", default="http://localhost:1234")
    # argparse rejects option-like values ("--agent-args --supervise"); fold the
    # value into the = form so both spellings work.
    argv, i = [], 0
    raw = sys.argv[1:]
    while i < len(raw):
        if raw[i] == "--agent-args" and i + 1 < len(raw):
            argv.append(f"--agent-args={raw[i + 1]}")
            i += 2
        else:
            argv.append(raw[i])
            i += 1
    args = ap.parse_args(argv)

    if args.trials < 1:
        ap.error("--trials must be at least 1")
    if args.timeout_scale <= 0:
        ap.error("--timeout-scale must be greater than 0")

    import shlex
    agent_args = shlex.split(args.agent_args)

    cfg = BenchConfig(
        trials=args.trials, levels=parse_levels(args.levels),
        tasks=[t.strip() for t in args.tasks.split(",") if t.strip()],
        oracle=args.oracle, keep_workdirs=args.keep_workdirs,
        agent_bin=args.agent_bin, agent_args=agent_args,
        timeout_scale=args.timeout_scale,
        lmstudio_url=args.lmstudio_url,
    )

    tasks = discover_tasks(cfg)
    if cfg.timeout_scale != 1.0:
        from dataclasses import replace
        tasks = [replace(t, timeout_s=int(t.timeout_s * cfg.timeout_scale),
                         request_timeout_s=int(t.request_timeout_s * cfg.timeout_scale))
                 for t in tasks]
    needs_node = any(t.frontend for t in tasks)
    needs_browser = any(t.frontend or "playwright" in t.graders for t in tasks)
    meta = preflight(cfg, needs_node, needs_browser)

    run_id = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    if not cfg.oracle and meta["model"]:
        run_id += f"_{meta['model']['key'].replace('/', '-')}"
    if cfg.agent_args:
        run_id += "_orchestrated"  # exact flags are in meta.agent_args
    run_scratch = cfg.scratch_root / "runs" / run_id
    run_scratch.mkdir(parents=True, exist_ok=True)
    out_root = cfg.results_dir / run_id
    out_root.mkdir(parents=True, exist_ok=True)

    node_modules = workspace.ensure_node_modules_cache(cfg.scratch_root) if needs_node else None

    results = {"run_id": run_id, "meta": meta, "trials": []}
    results_path = out_root / "results.json"
    total = len(tasks) * cfg.trials
    done = 0
    consecutive_crashes = 0
    for task in tasks:
        for trial_no in range(cfg.trials):
            done += 1
            print(f"[{done}/{total}] {task.id} trial {trial_no} … ", end="", flush=True)
            r = run_trial(task, trial_no, cfg, run_scratch, out_root, node_modules)
            results["trials"].append(r.to_dict())
            results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
            status = "RESOLVED" if r.resolved else (r.failure or "failed")
            print(f"{status}  score={r.score:.2f}  ({r.wall_s:.0f}s)")
            if r.failure and r.failure.startswith("agent-crashed"):
                consecutive_crashes += 1
                if consecutive_crashes >= 2:
                    sys.exit(f"\nAborting: the agent crashed on {consecutive_crashes} "
                             "consecutive trials — this is a setup problem, not a model "
                             f"result. See the traceback in "
                             f"{out_root / 'trials'}/<task>/agent.log")
            else:
                consecutive_crashes = 0

    report_path = report.write_report(results_path)
    if not cfg.keep_workdirs:
        shutil.rmtree(run_scratch, ignore_errors=True)

    task_stats = metrics.per_task(results["trials"])
    total_stats = metrics.overall(task_stats)
    print(f"\nOverall: score {total_stats['mean_score']:.2f} ± {total_stats['se']:.2f}, "
          f"pass@1 {total_stats['pass_at_1']:.2f} over {total_stats['tasks']} tasks")
    print(f"Report: {report_path}")
    if cfg.oracle:
        failed = [trial["task_id"] for trial in results["trials"]
                  if not trial["resolved"]]
        if failed:
            sys.exit(f"Oracle validation failed for {len(failed)} task(s): "
                     f"{', '.join(failed)}")


if __name__ == "__main__":
    main()
