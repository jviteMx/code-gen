# code-agent

A local, Claude-Code-style coding assistant. It started life inside `jira-tool`
and was pulled out into its own project so the coding workflow can stand alone,
with no Jira dependency.

There are two backends. Point it at **Anthropic Claude** (cloud) or at
**LMStudio** (a local, OpenAI-compatible server). Pick one in your config or with
`--provider`.

## Install

```bash
conda create -n code-agent python=3.12 && conda activate code-agent
pip install -e .            # editable install picks up source edits
pip install -e ".[dev]"     # adds pytest, ruff, mypy
```

This installs the `code-agent` and `ca` console scripts.

## Configure

Settings load with priority **CLI flags > env vars > TOML file**. Copy the
template and fill it in, or run the wizard:

```bash
cp .env.example .env        # then edit
# or:
code-agent configure        # writes ~/.config/code-agent/config.toml
```

`.env` is searched in `./`, `./.jt/`, then `~/.config/code-agent/`.

## Usage

```bash
code-agent                       # coding assistant in the current directory
code-agent /path/to/repo         # target a specific directory
code-agent . --no-plan           # skip plan mode
code-agent . --provider claude   # force backend for this session
code-agent . --prompt "add a healthcheck endpoint"
code-agent . --yes               # auto-approve plans (unattended)
code-agent . --no-stream         # disable streaming output
ca .                             # short alias
```

### The REPL

The input box is a real editor, and it tries to stay out of your way.

Enter sends the message. That's one keystroke, no double or triple Enter. If you
actually want a newline, use Alt+Enter. Pasting a multi-line traceback or code
block keeps its indentation and won't submit early; hit Enter once when you're
ready to send.

You can pull a file into your message with an `@path` mention (it tab-completes),
so you don't have to copy-paste files by hand. History is persistent (↑ and
Ctrl+R), slash commands complete, and the bottom toolbar shows mode, model, and
context usage. Type `/help` for the command list.

### Modes

The loop runs in three modes. `plan` gives the model read-only tools and asks for
a plan. `approve` waits for yes/no/revise (any extra words after `yes` are passed
along as guidance). `execute` opens up the full tool set. Plan mode is the
default; `--no-plan` executes directly and `--yes` auto-approves.

### What makes it good for local LLMs

Output streams as it's generated, so a slow local model doesn't feel dead, and
Ctrl+C cancels the current turn rather than the whole session.

`edit_file` is forgiving. It tries an exact match first, then a
whitespace/CRLF-tolerant match, and if it still can't find the text it shows a
"did you mean" snippet instead of failing silently. That keeps weaker models from
looping. It also supports `replace_all`.

Every write and edit prints a colored diff. Search uses ripgrep when `rg` is on
your PATH and falls back to a pure-Python scan otherwise, and file listing
respects `.gitignore`. Context tracking is accurate, with auto-compaction and
trimming that won't leave a tool result orphaned. If you want exact token counts,
`pip install -e ".[accurate-tokens]"` pulls in tiktoken.

## Workflow

The normal flow is Plan, Approve, Execute, then repeat.

1. **Start** with `code-agent .` (or a path). The banner shows the model, context
   window, mode, any rules it loaded, and a resumed session if there is one.
2. **Describe the task** at the `You [plan]:` prompt. The model pokes around with
   read-only tools and comes back with a numbered plan ending in
   `Ready to execute this plan? (yes/no/revise)`. If your request is ambiguous it
   asks a clarifying question first; just answer and it keeps planning.
3. **Approve** at the `Approve? (yes/no/revise):` prompt:
   - `yes` (also `y` / `go` / `approve`) executes. Anything after `yes` becomes
     extra guidance, e.g. `yes also add unit tests`.
   - `no` (also `n` / `cancel`) discards the plan and goes back to planning.
   - anything else is treated as revision feedback and the plan is redrafted.
4. **Execute.** The model implements with the full tool set and streams as it
   goes, printing a colored diff for each change. Ctrl+C cancels the current
   turn. When it's done it drops into `direct` mode so you can keep iterating; run
   `/plan` when you want to start a fresh feature.

**Faster paths.** Skip planning with `--no-plan` (or `/direct`) for a `You:`
prompt that implements right away. Run unattended with `--yes`, which
auto-approves plans and auto-authorizes agent spawns. And prefer `@path` over
pasting; tracebacks pasted directly still submit as a single message.

**Weaving in agents** (see [Multi-agent orchestration](#multi-agent-orchestration)).
`/panel <task>` has several models draft the plan and a judge pick or merge it
before you approve. `/supervise on` puts a second model on every plan and diff.
`/investigate a; b; c` gathers context from several parts of the codebase in
parallel. `/build <task>` is a one-shot implement, review, fix.

**Sessions persist.** The goal, plan, and progress are written to
`<workdir>/.jt/session.json`, so re-running `code-agent .` in the same directory
picks up where you left off. `/clear` wipes the conversation and memory.

## Multi-agent orchestration

The harness can spawn sub-agents, run them in parallel, and wire them into
supervisor, judge, and mixture-of-experts patterns. This pays off when LMStudio
is set to allow several concurrent requests, or when you load two different
models and have them check each other's work.

### Model assignment

The harness auto-detects the models loaded in LMStudio and spreads them across
roles, so if you have several loaded it just uses them. The **critic** and
**judge** each pick a different loaded model than the main one, so two models
really do supervise each other; with only one model loaded they reuse it.
`/panel` runs one proposer per loaded model, padding a single model with
temperature-varied copies for some diversity. Embedding models are never given a
chat role (more on the profiler below).

**Mixing Claude with local models.** With an Anthropic API key configured, Claude
shows up as a normal entry in the model list and can be pinned to any role. So
Claude can draft or judge the plan while local models do the agentic work, or
local models can implement while Claude reviews the diff:

```
/assign main 1              # e.g. Claude as the planner/main
/assign judge 1             # or Claude as the judge over local doers
/model 2                    # switch main to a local model
```

Auto-distribution stays within the main model's provider, so it won't quietly
start spending on the cloud. To cross providers, assign a role yourself with
`/assign`, `/model`, or `/suggest`. Read-only sub-agents (critic, judge,
proposers, explorers) each run on their own client, so a Claude role and a local
main coexist fine. Only switching the main model across providers resets the
conversation.

`/agents` shows the current arrangement and numbers each loaded model with its
capability tags. Pin a role yourself with `/assign`:

```
/agents                     # loaded models + tags + who does what
/assign critic 2            # role ← loaded model #2
/assign judge 3
/assign main 1
```

Run `/panel` with several models loaded and no roles pinned and it prints the
proposed arrangement and asks you to confirm (or type `assign` to customize),
unless you passed `--yes`.

### Model-aware suggestions (`/suggest`)

`/suggest [task]` asks one of your loaded models which models fit each role for
the task. There are no hardcoded name lists. It hands that model the full catalog
of available models (loaded and not) with their metadata (params, context, type,
vision) plus the task, and lets it reason over them.

It comes back with a `main` / `critic` / `judge` assignment, an `approach`
(`single` / `investigate` / `panel` / `review`), and a one-line reason. Embedding
models are never assigned a chat role, and that's validated in code even if the
model suggests one; hallucinated keys get corrected to a real loaded model. If a
recommended model isn't loaded, `/suggest` asks and then tells LMStudio to load
it (big models on CPU can take minutes, and Ctrl+C aborts). With no task
argument it uses your most recent message. If it can't reach any model to ask, it
falls back to a metadata heuristic, and says so.

### Preflight health-check

On startup, and any time you run `/preflight`, the harness pings each loaded chat
model with a 1-token request in parallel and reports how responsive each one is:

- `✗ no response` means the model crashed, OOM'd, or loaded badly (the error is
  included).
- `✓ responds, but SLOW (Ns)` means it's probably on CPU or heavily offloaded, so
  real runs will crawl.

Embedding models are skipped. It deliberately doesn't try to judge tool-use from
metadata, since LMStudio under-reports that. Turn the startup check off with
`--no-preflight`.

### Not getting stuck

Every request carries a timeout (`--timeout`, default 600s) as a backstop, and
Ctrl+C interrupts whatever is running, including parallel agents and a model
grinding away on CPU, and hands you back the prompt instead of hanging.

You can also pin roles up front with flags or config:

```bash
code-agent . --critic-model qwen2.5-coder-14b --judge-model llama-3.3-70b \
             --max-parallel 5 --supervise
```

The matching config keys (in `~/.config/code-agent/config.toml` or the
environment) are `critic_model`, `judge_model`, and `max_parallel_agents`. Leave
them empty and roles auto-distribute across loaded models as described above.

> **LMStudio tip:** set `LMSTUDIO_MODEL` to a real loaded model key, or leave it
> as `default`. The harness resolves `default` to whatever model is actually
> loaded and won't send the literal string `default`, which fails when several
> models are loaded.

The orchestration commands (`/panel`, `/review`, `/investigate`, `/build`,
`/supervise`, `/auto`, `/agents`) are listed in the [Command reference](#command-reference).

### Two ways to drive it

You can drive it yourself with the slash commands above plus `--supervise`. Or
you can let the model do it: the main model has a `dispatch_agents` tool to fan
out read-only investigation on its own, though the harness always asks your
permission before spawning. With `--auto` (or `/auto on`, which is off by
default), a model classifies each task and proposes investigate or panel only
when it actually fits. Summaries and reviews stay single-model.

### Safety model

Parallel sub-agents are read-only (explore, review, judge). The main session is
the only writer, so concurrent agents can't clobber each other's edits. That
covers supervision, judges, and MoE-for-planning.

Parallel writers, meaning several agents editing at once, each in its own git
worktree and then merged, are a planned future feature. They need worktree
isolation and a merge/pick step and aren't in v1.

## Command reference

### Input keys

| Key | Action |
|---|---|
| `Enter` | send the message |
| `Alt+Enter` | insert a newline (multi-line message) |
| `@path` | attach a file's contents (tab-completes) |
| `↑` / `↓`, `Ctrl+R` | history recall / reverse search |
| `Ctrl+C` | cancel the current turn (not the session) |
| paste | multi-line paste stays intact; press `Enter` once to send |

### Slash commands

Type `/help` in-session for this list. `off`-style toggles accept `on`/`off`.

**Session**

| Command | Action |
|---|---|
| `/help` | list all commands |
| `/clear` (or `clear`) | clear the conversation and session memory |
| `/quit` (or `quit` / `exit`) | end the session |
| `/continue` (`/c`) | continue where the model left off |

**Modes & planning**

| Command | Action |
|---|---|
| `/plan` | switch to plan mode (Plan → Approve → Execute) |
| `/direct` | switch to direct mode (implement immediately) |
| `/init` | analyze the codebase and generate a `PROJECT.md` rules file |

At the `Approve? (yes/no/revise):` prompt: `yes`/`y`/`go`/`approve` executes
(text after `yes` becomes extra guidance); `no`/`n`/`cancel` discards; anything
else is revision feedback.

**Context & memory**

| Command | Action |
|---|---|
| `/tokens` | token usage breakdown (system, conversation, remaining) |
| `/compact` | summarize older history to free context |
| `/memory` | show the persisted session memory (goal, plan, steps) |

**Models**

| Command | Action |
|---|---|
| `/models` | list available models (local **and** Claude) with params, context, loaded status |
| `/model N` (alias `/load N`) | set the main model to number `N` from `/models`. A model that is already loaded (or a cloud/Claude model) is selected in place with no reload; only an unloaded local model is loaded first. Updates the context window. |

Claude shows up in `/models` and `/agents` whenever an Anthropic API key is
configured, no matter which provider is the main one, so you can select or assign
it like any local model. If you pick a model from a different provider than the
current main, the conversation resets (the two backends use incompatible message
formats); your session memory stays.

**Multi-agent**

| Command | Action |
|---|---|
| `/agents` | show main/critic/judge models, parallel limit, numbered loaded models + tags |
| `/assign main\|critic\|judge <n>` | pin a role to loaded model number `<n>` (from `/agents`) |
| `/suggest [task]` | ask a loaded model to pick the best models per role for the task; offers to load missing ones |
| `/preflight` | ping loaded models; report responsiveness + latency |
| `/review [file]` | a critic model reviews the current plan, the recent diff, or a file → verdict + issues |
| `/panel <task>` (`/moe`) | several models draft a plan in parallel; a judge scores and synthesizes → becomes an approvable plan |
| `/investigate <a>; <b>; <c>` (`/explore`) | read-only explorers sweep areas in parallel; findings added to context (no `;` → auto-decomposed) |
| `/build <task>` (`/tdd`) | implement → a supervising model reviews the diff → fix (up to 2 rounds) |
| `/supervise on\|off` | auto-review every finalized plan and every executed diff with the 2nd model |
| `/auto on\|off` | let a model suggest an approach per task (off by default; asks before running) |

### CLI flags

| Flag | Effect |
|---|---|
| `--provider claude\|lmstudio` | force the backend for this session |
| `--prompt "…"` | seed the first message |
| `--no-plan` | start in direct mode |
| `--yes` | auto-approve plans and auto-authorize agent spawns |
| `--no-stream` | disable streaming output |
| `--context N` | override the context window size (tokens) |
| `--supervise` | start with supervise mode on |
| `--auto` | let a model suggest an approach per task (off by default) |
| `--no-preflight` | skip the startup model health-check |
| `--timeout N` | per-request timeout in seconds (default 600; backstop against hangs) |
| `--max-parallel N` | cap parallel sub-agents (match your LMStudio limit; default 5) |
| `--critic-model KEY` | model for the critic/reviewer agent |
| `--judge-model KEY` | model for the judge agent |

## Rules

User-authored rules are injected into the system prompt, merged in order:

1. Global: `~/.config/code-agent/rules.md` (falls back to the legacy
   `~/.config/jira-tool/rules.md` if present)
2. Project: the first of `PROJECT.md` / `.jt-rules` / `JT.md` found walking up
   from the working directory to the git root

## Layout

```
code-agent/
  pyproject.toml
  .env / .env.example
  tests/                  # pytest: tool executor, tokens, LLM shapes, mentions
  src/code_agent/
    cli.py                # entry point (path arg, configure subcommand)
    config.py             # layered config (provider + model endpoints)
    lmstudio.py           # LMStudio REST management (list/load/query models)
    coder/
      loop.py             # run_coding_session — builds everything, stable API
      session.py          # CoderSession: state machine, command registry, tool loop
      orchestration.py    # sub-agents, parallel(), critic/judge/MoE patterns
      model_profiler.py   # classify models (code/reason/vision/embed) + role router
      llm.py              # LLMClient abstraction (streaming) over OpenAI + Anthropic
      ui.py               # prompt_toolkit REPL + rich rendering (diffs, streaming)
      prompts.py          # system prompts + a placeholder-safe renderer
      coding_tools.py     # tool schemas
      tool_executor.py    # file ops + shell; forgiving edits, ripgrep search
      token_counter.py    # context tracking, trimming, optional tiktoken
      session_memory.py   # goal/plan/steps persisted across trims & restarts
      rules.py            # global + project rule loading
```

## Architecture

`loop.run_coding_session()` builds an `LLMClient` (`OpenAIClient` for LMStudio or
`AnthropicClient`), a `ReplUI`, a `CodingToolExecutor`, `SessionMemory`, and a
`TokenTracker`, then hands them to a `CoderSession`. The session owns the
plan→approve→execute state machine, a slash-command registry, and the agentic
tool loop (streaming, context management, stall self-check).

The `llm` module is the only place that knows each vendor's wire format. The loop
speaks a normalized `Turn(content, tool_calls)`, and each client writes history
back in its vendor's shape. One thing to watch: all of a turn's Anthropic
`tool_result` blocks go into a single user message.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## License

This is source-available software, not open source in the OSI sense.

The source code is available under the
[PolyForm Noncommercial License 1.0.0](./LICENSE). Personal, educational,
research, and other permitted noncommercial uses are allowed under that license.

Commercial use requires a separate commercial license. See
[COMMERCIAL-LICENSE.md](./COMMERCIAL-LICENSE.md), or contact Javier Vite via
LinkedIn to arrange one:
<https://www.linkedin.com/in/yobbahim-j-vite-b621bb221/>

