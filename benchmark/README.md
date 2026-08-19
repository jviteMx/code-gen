# code-agent benchmark

Measures how well `code-agent` + the currently loaded LM Studio model solves coding
tasks of increasing scope against a deterministic template web app ("Kanbanlite":
FastAPI + SQLite backend, React/Vite frontend).

Seven levels, 18 tasks: **L1** function · **L2** class · **L3** module · **L4**
service · **L5** API contract · **L6** frontend/CSS · **L7** architecture.
Scoring and references: [`CRITERIA.md`](CRITERIA.md).

## Requirements

| What | Why | Check with |
|---|---|---|
| Python ≥ 3.10 | runs the harness and the graded template backend | `python --version` |
| The code-agent **repo** (editable install) | `benchmark/` ships in the repo, not the wheel | `pip show code-agent` says `Editable project location: …` |
| Node.js ≥ 20 on PATH | builds the template's React frontend (`npm`) | `node --version` |
| Git on PATH | per-trial baselines and diff metrics | `git --version` |
| LM Studio with the local server enabled | serves the model under test | the `Developer → Server` toggle, default port 1234 |
| ~1 GB free disk | chromium browser (~120 MB) + npm cache + trial workspaces | — |

Works on **native Windows** and **Linux/WSL2**. If you run code-agent from Windows
Python (the usual setup when LM Studio runs on Windows), install everything below in
that same Windows environment — a WSL install won't be visible to it, and vice versa.

## Installation

```bash
cd code-agent
pip install -e ".[bench]"
```

That's the whole manual part. Two more downloads happen **automatically on your
first run**:

1. **Playwright's chromium** (~120 MB, one-time) — the preflight detects it's missing,
   prints `downloading it now…`, and fetches it into a user-level cache
   (`%LOCALAPPDATA%\ms-playwright` on Windows, `~/.cache/ms-playwright` on Linux)
   shared by all your virtualenvs. This can't live in `pyproject.toml`: browser
   binaries aren't Python packages, and wheels have no post-install hooks.
   *Linux/WSL only:* if chromium still fails to launch afterwards, the OS libraries
   are missing — run `sudo playwright install-deps chromium` once (needs root, so
   it's never automated).
2. **The template frontend's `node_modules`** — one `npm ci` (~30–60 s), cached under
   `~/.cache/code-agent-bench/npm/` and hardlinked into every trial afterwards.

If the harness is missing a Python dependency it exits immediately with the exact
`pip install` command to run — you never have to guess from a traceback.

Scratch space (trial workspaces, npm cache, grading DBs) lives under
`~/.cache/code-agent-bench` (`%USERPROFILE%\.cache\code-agent-bench` on Windows).
On WSL2 that native-filesystem location is mandatory — SQLite misbehaves on
`/mnt/*` — so don't relocate it.

**Load only the model under test.** A second resident model competes for VRAM,
inflates wall times, and can flip trials to timeout. The preflight warns when it
detects extra loaded chat models and records them in `results.json`
(`meta.loaded_models`) so confounded runs are visible; unload extras first
(`/model N` on that model toggles it unloaded).

## Running

**From inside a code-agent session** (easiest — benchmarks whatever main model you
picked, and pins it for every trial):

```
/models          # list models
/model 2         # choose the one to test
/benchmark       # full suite; args pass through: --trials 3, --levels 1-3, oracle…
```

**Standalone**, with a chat model loaded in LM Studio (server enabled):

```bash
cd code-agent
python -m benchmark.harness.run                     # all 18 tasks, 1 trial each
python -m benchmark.harness.run --trials 3          # statistically meaningful run
python -m benchmark.harness.run --levels 1-3        # subset by level
python -m benchmark.harness.run --tasks L4-01,L6-02 # specific tasks
python -m benchmark.harness.run --keep-workdirs     # keep trial dirs for debugging
```

The standalone runner tests the first loaded chat model unless `LMSTUDIO_MODEL` is
set to a specific model key (that's how `/benchmark` pins the session's model). The
agent subprocesses are forced to the LM Studio provider regardless of the user's
config, and inherit `--lmstudio-url`.

**Benchmarking orchestrated configurations.** By default the suite scores the bare
agent loop, so results are attributable to one model. `--agent-args` passes extra
flags to every trial's `code-agent` invocation, letting you score a model *plus* an
orchestration setup:

```bash
python -m benchmark.harness.run --agent-args="--supervise" --trials 3
python -m benchmark.harness.run --agent-args="--supervise --critic-model KEY --max-parallel 2"
# in-session: /benchmark --agent-args "--supervise"
```

Orchestrated runs get an `_orchestrated` suffix on the results directory, record the
exact flags in `meta.agent_args`, and the report is labeled accordingly. Comparing
one against a bare-loop run measures the value of the **whole workflow**, not a
model-only capability difference. Multi-model orchestration can load several models
at once, which is exactly the VRAM-contention case the preflight warns about: expect
slower wall times on single-GPU machines.

Useful workflow flags (all combinable):

| Flag | Workflow |
|---|---|
| `--plan` | plan → auto-approve → execute (re-enables plan mode over the harness's `--no-plan` default) |
| `--supervise` | a critic model reviews every plan and diff; with one model loaded it self-reviews, with two it cross-reviews |
| `--critic-model KEY` | pin which model does the critic reviews |
| `--auto` | the model picks an orchestration pattern per task (a routing policy): a suggested plan-panel auto-executes under `--yes`; a suggested investigation runs first and the task is then implemented with the findings in context |

Orchestration multiplies request counts, and big offloaded models are slow to begin
with — stretch the time budget with `--timeout-scale` so you measure capability, not
the clock: `--timeout-scale 3` triples every task's wall/request timeouts (recorded
in `meta.timeout_scale`; wall-time medians across different scales aren't comparable,
scores are).

**Does orchestration close the gap? The experiment matrix** (one model loaded at a
time, `--trials 3`, same timeout scale everywhere):

```
/benchmark --trials 3 --timeout-scale 3                                 # bare loop (baseline)
/benchmark --trials 3 --timeout-scale 3 --agent-args "--plan"           # plan→execute
/benchmark --trials 3 --timeout-scale 3 --agent-args "--plan --supervise"  # + self-critic
```

Run the matrix per model, then compare each configuration's pass@1 against the same
model's baseline (paired per-task, per `CRITERIA.md` §4). Watch `median requests` in
the reports: orchestration must buy its extra tokens with resolved tasks.

The harness records the loaded model's identity (key, params, quantization) in the
results, so comparing models is just: load model A → run → swap to model B in
LM Studio → run again. Results accumulate under `benchmark/results/<run_id>/`:

- `results.json` — all trial data (machine-readable, keeps per-task means for paired
  model comparisons)
- `report.md` — per-level and per-task tables, pass@1, mean ± SE, failure taxonomy
- `trials/<task>-t<n>/` — `agent.log`, `diff.patch`, `grade.json` per trial

## Reading the results

**`resolved` / pass@1 is the headline** ("would I trust it to finish the job"): every
hidden fail-to-pass test passes AND the full regression suite stays green. The
*score* adds partial credit and is best read in bands:

| Score band | Meaning |
|---|---|
| **0.30** | The floor, not "30% solved": build gate (0.1) + regression suite untouched (0.2). The agent made no useful change and quit. |
| **0.4 – 0.7** | Real partial progress — some hidden tests pass. |
| **0.8 – 0.95** | Near-miss: most hidden tests pass, one behavior or detail missing. |
| **0.96 – 1.00** | Solved; fractions lost to minimality (diff bigger than reference) or localization (touched files outside the allowlist). |

**Failure taxonomy values** (report's last table, and `failure` in `results.json`):

| Failure | Meaning |
|---|---|
| `f2p-fail` | Ran to completion but hidden tests fail — a genuine capability miss. Check the f2p subscore: 0.8+ is a near-miss, 0.0 means it never engaged. |
| `p2p-regression` | Solved the task but broke existing behavior. |
| `gate-fail` | Left the app uncompilable / frontend unbuildable. |
| `wall-timeout` | Killed at the task's time budget — check the subscores; a high f2p here means time-starved, not incapable (use `--timeout-scale`). The kill lands mid-edit, so p2p < 1 is common. |
| `stalled` | code-agent's repeat/stall detector ended the session (model looping). |
| `agent-crashed (exit N)` | The agent process died before working — a setup problem, never a model result; see `agent.log`. Two in a row abort the run. |
| `context-exhausted` / `api-error` | Inferred from the agent log tail; infrastructure-flavored failures. |

**Before comparing two runs, check `results.json → meta`:** `loaded_models` (must
contain ONLY the model under test), `loaded_context_length` (≥16k), `agent_args`
(bare loop vs orchestrated — never cross-compare), `timeout_scale` (scores
comparable across scales, wall times not), `trials_per_task` (single-trial pass@1
moves by whole tasks — treat n=1 as directional, use `--trials 3` before concluding).

Per-trial evidence lives in `trials/<task>-t<n>/`: `agent.log` (the full session —
read this to see *why* a task failed), `diff.patch` (what it changed), `grade.json`
(subscores + detail), junit XMLs, `schemathesis.log`, `server.log`.

## Validating the benchmark itself (no model needed)

```bash
python -m benchmark.harness.run --oracle            # applies each task's reference
                                                    # patch; must resolve 18/18 at 1.00
```

Run this after any change to the template app, a task's tests, or the grader.

## How a trial works

1. Copy `template_app/` to a scratch dir (ext4), hardlink the cached `node_modules`,
   `git init` + baseline commit.
2. Invoke `code-agent <dir> --oneshot --prompt <task> --yes --no-plan --no-preflight
   --no-stream --max-parallel 1` under a wall-clock timeout (SIGTERM→SIGKILL of the
   whole process group on expiry).
3. Commit the result; compute diff metrics; restore `backend/tests/` if tampered.
4. Inject the hidden fail-to-pass tests (which were absent from the trial workspace),
   run all graders (pytest, Playwright against
   a served build, schemathesis against `/openapi.json`), score, tear down.

## Troubleshooting

| Symptom | Cause → fix |
|---|---|
| `ModuleNotFoundError: No module named 'yaml'` (or fastapi/playwright/…) | The `[bench]` extra isn't installed **in the Python environment you're running from**. `pip install -e ".[bench]"` there. Newer harness versions print this fix instead of a traceback. |
| `Playwright chromium unavailable` and the auto-download didn't help | Linux/WSL missing system libraries: `sudo playwright install-deps chromium` (once). On Windows check that `%LOCALAPPDATA%\ms-playwright` is writable. |
| `LM Studio not reachable at http://localhost:1234` | Start LM Studio and enable the local server (Developer → Server). If code-agent runs in WSL but LM Studio on Windows, localhost won't cross the boundary — enable "Serve on Local Network" and pass `--lmstudio-url http://<windows-ip>:1234`. |
| `no chat model loaded in LM Studio` | Load a model in LM Studio first (or `/model N` in code-agent). Embedding models don't count. |
| `loaded with only 4,096 tokens of context` (or a NOTE about undetectable context) | LM Studio's JIT/API default context is 4096 — far too small for the agent's tool loop, so the preflight refuses to produce meaningless scores. Reload the model with 16384+ context: LM Studio → My Models → model settings → context length, or load it via code-agent's `/model N`, which requests 32k automatically. |
| `pinned model '<key>' not found` | The session's main model was unloaded between `/model` and `/benchmark`. Re-select it with `/models`, `/model N`. |
| `WARNING: other chat models are loaded alongside …` | Not fatal, but wall times (and possibly timeouts) are being skewed by VRAM contention. Unload the extras: `/model N` on each (toggles unloaded). The run is flagged in `results.json → meta.loaded_models`. |
| `'code-agent' not found in PATH` | The console script isn't installed in this environment: `pip install -e .` (the benchmark spawns the real CLI per trial). |
| `npm not found — Node >= 20 is required` | Install Node 20+ and reopen the terminal so PATH refreshes. On Windows, install the Windows build (a WSL node is invisible to Windows Python). |
| A trial shows `wall-timeout` | The model ran past the task's `timeout_s`. Slow/CPU-spilled models do this — check the contention warning above, or raise `timeout_s` in the task's `task.yaml` if your hardware is simply slower. |
| Oracle run doesn't resolve 18/18 | Something in `template_app/`, a task's tests, or the grader changed incompatibly. Diagnose from `benchmark/results/<run>/trials/<task>-t0/` (`grade.json`, junit XMLs, `schemathesis.log`, `server.log`). |

## Adding a task

Create `tasks/L<n>/<ID>/` with `prompt.md`, `task.yaml` (see any existing one),
`f2p/backend/*.py` and/or `f2p/playwright/*.py`, and a `reference.patch` (a `git
diff` against the pristine template). Then verify both directions:

1. `python -m benchmark.harness.run --oracle --tasks <ID>` → must resolve at 1.00.
2. The F2P tests must FAIL on the unpatched template (inject them into a fresh copy
   and run pytest — the harness's task-authoring check in git history shows the
   pattern).

Keep P2P compatibility in mind: every committed template test must pass on the
pristine app AND under your reference patch (use `p2p_ignore` in `task.yaml` only for
deliberate contract breaks).
