"""Interactive coding session: the plan/approve/execute state machine, slash
commands, and the agentic tool loop."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from code_agent.coder import model_profiler as mp
from code_agent.coder import orchestration as orch
from code_agent.coder import prompts
from code_agent.coder.coding_tools import (
    CODING_TOOLS,
    DISPATCH_AGENTS_TOOL,
    PLAN_TOOL_NAMES,
    to_openai_format,
)
from code_agent.coder.llm import LLMClient
from code_agent.coder.rules import load_all_rules
from code_agent.coder.session_memory import SessionMemory
from code_agent.coder.token_counter import (
    TokenTracker,
    count_message_tokens,
    trim_messages_to_fit,
)
from code_agent.coder.tool_executor import CodingToolExecutor
from code_agent.coder.ui import ReplUI, expand_file_mentions

PROGRESS_TOOL_NAMES = {"write_file", "edit_file", "update_memory", "install_package"}
CYCLE_SOFT_CHECK_ROUNDS = 8
CYCLE_SOFT_CHECK_INTERVAL = 8
AUTO_POLICY_VERSION = "auto-v2"
AUTO_ROUTE_CONFIDENCE = 0.60


@dataclass
class RouteDecision:
    approach: str = "single"
    confidence: float = 0.0
    parallelism: int = 1
    signals: list[str] = field(default_factory=list)
    reason: str = ""


def _to_anthropic(tools: list[dict]) -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
            for t in tools]


class CoderSession:
    def __init__(self, *, client: LLMClient, ui: ReplUI, executor: CodingToolExecutor,
                 memory: SessionMemory, tracker: TokenTracker, workdir: str,
                 context: str = "", rules: str = "", plan_mode: bool = True,
                 auto_approve: bool = False, stream: bool = True,
                 lmstudio_url: str = "http://localhost:1234/v1",
                 max_parallel_agents: int = 5, critic_model: str = "",
                 judge_model: str = "", supervise: bool = False,
                 auto_orchestrate: bool = False, registry=None) -> None:
        self.client = client
        self.registry = registry
        self.ui = ui
        self.executor = executor
        self.memory = memory
        self.tracker = tracker
        self.workdir = workdir
        self.context = context
        self.rules = rules
        self.plan_mode = plan_mode
        self.auto_approve = auto_approve
        self.stream = stream
        self.lmstudio_url = lmstudio_url

        self.max_parallel_agents = max(1, max_parallel_agents)
        self.critic_model = critic_model
        self.judge_model = judge_model
        self.supervise = supervise
        self.auto_orchestrate = auto_orchestrate

        self.mode = "plan" if plan_mode else "direct"
        self.messages: list[dict] = []
        self.current_plan: str | None = None
        self.recent_diffs: list[str] = []  # applied since the last review
        self._routing: dict = {
            "policy_version": AUTO_POLICY_VERSION,
            "enabled": auto_orchestrate,
            "events": [],
        }
        self._auto_runtime = {"verification_failures": 0, "localization_errors": 0,
                              "stalled": False}

        self._rebuild_tools()

        self.ui.set_status_provider(self._toolbar_status)
        self._commands = self._build_commands()

    def _rebuild_tools(self) -> None:
        """Build the plan/exec tool schemas in the main client's wire format.

        Re-run on any provider switch; the Anthropic and OpenAI schemas differ.
        """
        plan_tools = [t for t in CODING_TOOLS if t["name"] in PLAN_TOOL_NAMES]
        exec_tools = CODING_TOOLS + [DISPATCH_AGENTS_TOOL]
        if self.client.name == "claude":
            self.tools_all = _to_anthropic(exec_tools)
            self.tools_plan = _to_anthropic(plan_tools)
        else:
            self.tools_all = to_openai_format(exec_tools)
            self.tools_plan = to_openai_format(plan_tools)

    # ── status ────────────────────────────────────────────────────────

    def _toolbar_status(self) -> str:
        t = self.tracker
        return f"{self.mode} · {self.client.model} · ctx {t.usage_percent:.0f}% ({t.used_tokens}/{t.context_window})"

    def _active_system(self, template: str, **extra) -> str:
        """Render a phase prompt and refresh the system-token count."""
        prompt = prompts.render(
            template, workdir=self.workdir, rules=self.rules,
            memory=self.memory.format_for_prompt(), context=self.context, **extra,
        )
        tools = self.tools_plan if self.mode == "plan" else self.tools_all
        self.tracker.set_system_tokens(prompt, tools)
        return prompt

    # ── main loop ───────────────────────────────────────────────────────

    def run(self) -> None:
        while True:
            try:
                user_input = self.ui.read(self.mode)
            except (KeyboardInterrupt, EOFError):
                self.ui.info("\nSession ended.")
                break

            if not user_input:
                continue

            # Ctrl+C during an operation drops back to the prompt; at the prompt
            # (handled above) it ends the session.
            try:
                if user_input.startswith("/") or user_input.lower() in ("quit", "exit", "clear"):
                    if self._dispatch_command(user_input):
                        continue

                if self.mode == "approve":
                    self._handle_approval(user_input)
                    continue

                if self._maybe_suggest(user_input):
                    continue

                if self.mode == "plan":
                    self._handle_plan(user_input)
                else:
                    self._handle_direct(user_input)
            except KeyboardInterrupt:
                self.ui.warn("\n[cancelled] back to the prompt.")

    def run_oneshot(self, prompt: str) -> None:
        """Handle a single task headlessly and return (no REPL)."""
        try:
            # --auto: let a model pick an orchestration pattern first. The panel
            # path ends in approve mode with a plan; investigation just leaves
            # findings in context for the normal dispatch below.
            if self._maybe_suggest(prompt) and self.mode == "approve":
                if self.current_plan:
                    self._handle_approval("yes")
                    return
                self.mode = "plan" if self.plan_mode else "direct"
            if self.mode == "plan":
                self._handle_plan(prompt)
            else:
                self._handle_direct(prompt)
        except KeyboardInterrupt:
            self.ui.warn("\n[cancelled]")

    # ── command registry ─────────────────────────────────────────────────

    def _build_commands(self) -> dict:
        return {
            "quit": self._cmd_quit, "exit": self._cmd_quit, "/quit": self._cmd_quit,
            "clear": self._cmd_clear, "/clear": self._cmd_clear,
            "/help": self._cmd_help,
            "/plan": self._cmd_plan, "/direct": self._cmd_direct,
            "/memory": self._cmd_memory, "/tokens": self._cmd_tokens,
            "/compact": self._cmd_compact, "/continue": self._cmd_continue, "/c": self._cmd_continue,
            "/init": self._cmd_init, "/models": self._cmd_models,
            "/load": self._cmd_load, "/model": self._cmd_load,
            # orchestration
            "/agents": self._cmd_agents, "/assign": self._cmd_assign,
            "/suggest": self._cmd_suggest, "/preflight": self._cmd_preflight,
            "/review": self._cmd_review,
            "/panel": self._cmd_panel, "/moe": self._cmd_panel,
            "/investigate": self._cmd_investigate, "/explore": self._cmd_investigate,
            "/build": self._cmd_build, "/tdd": self._cmd_build,
            "/supervise": self._cmd_supervise, "/auto": self._cmd_auto,
            "/benchmark": self._cmd_benchmark, "/bench": self._cmd_benchmark,
        }

    def _dispatch_command(self, text: str) -> bool:
        key = text.split(None, 1)[0].lower()
        handler = self._commands.get(key)
        if handler is None:
            if text.startswith("/"):
                self.ui.warn(f"Unknown command: {key}. Type /help.")
                return True
            return False
        arg = text[len(key):].strip()
        handler(arg)
        return True

    def _cmd_quit(self, arg: str) -> None:
        self.ui.info("Session ended.")
        raise SystemExit(0)

    def _cmd_clear(self, arg: str) -> None:
        self.messages.clear()
        self.current_plan = None
        self.memory.clear()
        self.mode = "plan" if self.plan_mode else "direct"
        self.ui.success("Conversation and memory cleared.")

    def _cmd_help(self, arg: str) -> None:
        from code_agent.coder.ui import SLASH_COMMANDS
        self.ui.rule("commands")
        for cmd, desc in SLASH_COMMANDS.items():
            self.ui.console.print(f"  [cyan]{cmd}[/cyan]  [grey58]{desc}[/grey58]")
        self.ui.console.print("  [grey58]Enter=send · Alt+Enter=newline · @path attaches a file[/grey58]")

    def _cmd_plan(self, arg: str) -> None:
        self.mode = "plan"
        self.ui.info("Switched to plan mode.")

    def _cmd_direct(self, arg: str) -> None:
        self.mode = "direct"
        self.ui.info("Switched to direct mode (no planning).")

    def _cmd_memory(self, arg: str) -> None:
        text = self.memory.format_for_prompt()
        self.ui.console.print(f"\n{text}\n" if text else "  No session memory yet.")

    def _cmd_tokens(self, arg: str) -> None:
        t = self.tracker
        self.ui.status_line(t.format_status())
        self.ui.info(f"  System prompt + tools: ~{t.system_tokens:,} tokens")
        self.ui.info(f"  Conversation: ~{count_message_tokens(self.messages):,} tokens")
        self.ui.info(f"  Remaining: ~{t.remaining_tokens:,} tokens")

    def _cmd_compact(self, arg: str) -> None:
        if not self.messages:
            self.ui.info("Nothing to compact yet.")
            return
        self.ui.warn("[Compacting conversation…]")
        old = self.tracker.used_tokens
        result = self._compact(self.messages)
        if result is None:
            self.ui.info("Not enough history to compact.")
            return
        new_messages, summary = result
        self.messages[:] = new_messages
        self.tracker.record_request(self.messages)
        freed = max(0, old - self.tracker.used_tokens)
        self.ui.success(f"Compacted. Freed ~{freed:,} tokens.")
        self.ui.status_line(self.tracker.format_status())
        self.ui.info("  " + summary[:500].replace("\n", "\n  "))

    def _cmd_continue(self, arg: str) -> None:
        self.messages.append({"role": "user",
                              "content": "Continue where you left off. Keep going with the implementation."})
        system = self._active_system(prompts.CODING_SYSTEM_PROMPT)
        self._tool_loop(system, self.messages, self.tools_all)

    def _cmd_init(self, arg: str) -> None:
        from pathlib import Path
        existing = next((Path(self.workdir) / f for f in ("PROJECT.md", ".jt-rules", "JT.md")
                         if (Path(self.workdir) / f).exists()), None)
        if existing:
            try:
                confirm = input(f"  {existing.name} exists. Overwrite? (y/N): ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                confirm = "n"
            if confirm not in ("y", "yes"):
                self.ui.info("/init cancelled.")
                return
        self.ui.success("Analyzing codebase and generating PROJECT.md…")
        system = self._active_system(prompts.INIT_SYSTEM_PROMPT)
        init_messages = [{"role": "user",
                          "content": "Analyze this project and write PROJECT.md at the repo root per the system prompt."}]
        self._tool_loop(system, init_messages, self.tools_all)
        self.rules = load_all_rules(self.workdir)
        self.ui.success("/init complete. Project rules reloaded.")

    def _cmd_models(self, arg: str) -> None:
        models = self._all_models()
        if not models:
            self.ui.warn("No models found. Is the LMStudio server running / a Claude key set?")
            return
        self.ui.models_table(models)
        self.ui.info("To use one as the main model: /model <number>  (already-loaded models are just selected).")

    def _cmd_load(self, arg: str) -> None:
        """Make model N the main model (`/model N`, alias `/load N`).

        Already-loaded local models and cloud models are selected in place;
        an unloaded LMStudio model gets loaded first. After a switch away from
        a loaded local model you're asked whether to unload it (VRAM is finite);
        `/model N` on the current main model toggles it: confirms and unloads.
        """
        models = self._all_models()
        if not models:
            self.ui.warn("No models available. Is the LMStudio server running / a Claude key set?")
            return
        try:
            idx = int(arg.split()[0]) - 1
        except (ValueError, IndexError):
            self.ui.info("Usage: /model <number> (see /models). Repeat on the current main to unload it.")
            return
        if not (0 <= idx < len(models)):
            self.ui.warn("Invalid model number.")
            return
        target = models[idx]

        from code_agent.lmstudio import LMStudioManager
        mgr = LMStudioManager(self.lmstudio_url)
        prev_key = self.client.model if self.client.name == "lmstudio" else None

        # Toggle: /model N on the model that is already the main → unload it.
        if (target.get("provider") != "claude" and target.get("loaded")
                and prev_key == target["key"]):
            if not self._confirm(f"{target['display_name']} is the current main model. Unload it?",
                                 default=True):
                return
            result = mgr.unload_model(target["key"])
            if not result.get("success"):
                self.ui.error(f"Unload failed: {result.get('error', 'unknown error')} "
                              "(the model is still loaded)")
                return
            self.ui.success(f"Unloaded {target['display_name']}.")
            self._fallback_main(exclude_key=target["key"])
            return

        # Cloud model or an already-loaded local model: just select it.
        if target.get("provider") == "claude" or target.get("loaded"):
            self._select_main(target)
            where = "cloud" if target.get("provider") == "claude" else "already loaded"
            self.ui.success(f"Main model → {target['display_name']} ({where}).")
            # Both models stay resident on purpose (orchestration can use both),
            # but offer the unload since VRAM contention is the common footgun.
            self._offer_unload_previous(mgr, models, prev_key, target, default=False)
            return

        # Unloaded LMStudio model: load it, then select. LMStudio's own default
        # context is a useless 4096, so ask for more (capped by the model's max).
        from code_agent.lmstudio import DEFAULT_LOAD_CONTEXT
        want_ctx = min(DEFAULT_LOAD_CONTEXT, target.get("max_context_length") or DEFAULT_LOAD_CONTEXT)
        self.ui.info(f"Loading {target['display_name']} (requesting {want_ctx:,} ctx)… "
                     "[grey58](big models on CPU can take minutes; Ctrl+C to abort)[/grey58]")
        try:
            result = mgr.load_model(target["key"], context_length=want_ctx)
        except KeyboardInterrupt:
            self.ui.warn("Load aborted.")
            return
        if result.get("success"):
            effective = result.get("context_length")
            if effective:
                target = {**target, "max_context_length": effective}
            self._select_main(target)
            if effective:
                self.ui.success(f"Loaded and selected. Context: {effective:,} tokens.")
                if effective < want_ctx:
                    self.ui.warn(f"Server loaded only {effective:,} of the requested "
                                 f"{want_ctx:,} — raise the model's context in "
                                 "LM Studio's per-model settings for agentic work.")
            else:
                self.ui.success("Loaded and selected.")
                self.ui.warn(f"Couldn't confirm the effective context (requested {want_ctx:,}). "
                             "LMStudio's API default is 4096 — check the model's context in "
                             "LM Studio's settings; agentic work needs 16k+.")
            self._offer_unload_previous(mgr, models, prev_key, target, default=True)
        else:
            self.ui.error(f"Failed: {result.get('error', 'unknown error')}")

    def _confirm(self, prompt: str, default: bool) -> bool:
        suffix = "[Y/n]" if default else "[y/N]"
        try:
            ans = input(f"  {prompt} {suffix} ").strip().lower()
        except (EOFError, KeyboardInterrupt, OSError):
            return False  # non-interactive stdin: never unload unattended
        if not ans:
            return default
        return ans in ("y", "yes")

    def _offer_unload_previous(self, mgr, models: list[dict], prev_key: str | None,
                               target: dict, default: bool) -> None:
        """After switching main away from a loaded local model, offer to unload it."""
        if not prev_key or prev_key in ("default", target.get("key")):
            return
        prev = next((m for m in models
                     if m.get("key") == prev_key and m.get("loaded")
                     and m.get("provider") != "claude"), None)
        if prev is None:
            return
        if self._confirm(f"Unload the previous model {prev['display_name']} to free VRAM? "
                         "(keep it for multi-model orchestration)", default=default):
            result = mgr.unload_model(prev_key)
            if result.get("success"):
                self.ui.success(f"Unloaded {prev['display_name']}.")
            else:
                self.ui.error(f"Unload failed: {result.get('error', 'unknown error')} "
                              "(the model is still loaded)")

    def _fallback_main(self, exclude_key: str) -> None:
        """After unloading the main model, point main at another loaded chat model."""
        candidates = [m for m in self._all_models()
                      if m.get("loaded") and m.get("provider") != "claude"
                      and m.get("key") != exclude_key and not mp.profile(m).is_embedding]
        if candidates:
            self._select_main(candidates[0])
            self.ui.info(f"Main model → {candidates[0]['display_name']}.")
        elif self.registry is not None and self.registry.has_claude():
            self.ui.warn("No local model loaded. Claude is available — select it with /models, /model N.")
        else:
            self.ui.warn("No model loaded now. Use /models then /model N to load one.")

    def _select_main(self, model: dict) -> None:
        """Point the main model at `model`, routing to its provider's client.

        A provider change resets the conversation, the two backends can't share
        message history.
        """
        new_client = self._client_for(model["key"])
        provider_changed = new_client.name != self.client.name
        self.client = new_client
        self.client.model = model["key"]
        self._rebuild_tools()
        if model.get("max_context_length"):
            self.tracker.context_window = model["max_context_length"]
        if provider_changed and self.messages:
            self.messages.clear()
            self.current_plan = None
            self.ui.warn("Provider changed, conversation history reset "
                         "(backends use different message formats). Session memory kept.")

    # ── orchestration commands ────────────────────────────────────────────

    def _cmd_agents(self, arg: str) -> None:
        self.ui.rule("agents")
        c = self.ui.console
        crit, crit_auto = self._eff_role(self.critic_model, {self.client.model})
        judge, judge_auto = self._eff_role(self.judge_model, {self.client.model, crit})
        def tag(auto: bool) -> str:
            return " [grey50](auto)[/grey50]" if auto else ""
        c.print(f"  [grey58]main[/grey58]   {self.client.model}")
        c.print(f"  [grey58]critic[/grey58] {crit}{tag(crit_auto)}")
        c.print(f"  [grey58]judge[/grey58]  {judge}{tag(judge_auto)}")
        c.print(f"  [grey58]max parallel[/grey58] {self.max_parallel_agents}   "
                f"[grey58]supervise[/grey58] {'on' if self.supervise else 'off'}   "
                f"[grey58]auto-suggest[/grey58] {'on' if self.auto_orchestrate else 'off'}")
        loaded = self._loaded_models()
        if loaded:
            c.print("  [grey58]loaded models:[/grey58]")
            for i, m in enumerate(loaded, 1):
                p = mp.profile(m)
                mark = " [green]●[/green]" if m["key"] == self.client.model else "  "
                warn = " [yellow](embedding, not for chat)[/yellow]" if p.is_embedding else ""
                cloud = " [cyan](cloud)[/cyan]" if m.get("provider") == "claude" else ""
                c.print(f"   {i:2d}.{mark} {m['display_name']} "
                        f"[grey58]({p.tags()}, {m['max_context_length']:,} ctx)[/grey58]{cloud}{warn}")
            self.ui.info("  /assign main|critic|judge <n> · /suggest to auto-pick · /preflight to health-check")
        elif self.client.name == "lmstudio":
            self.ui.warn("  No loaded models found. Is the LMStudio server running?")
        self.ui.info("  /review · /panel <task> · /investigate <a; b; c> · /build <task> · /supervise on|off")

    def _cmd_suggest(self, arg: str) -> None:
        models = self._all_models()
        if not models:
            self.ui.warn("No models found. Is the LMStudio server running / a Claude key set?")
            return
        task = arg.strip() or self._recent_task() or "general coding, review, and analysis in this project"
        self.ui.info("[suggest] asking a loaded model to match models to the task…")
        rec = self._llm_recommend(task, models)
        source = "model"
        if not rec:  # no model reachable to ask
            profiles = [mp.profile(m) for m in models]
            heur = mp.recommend(profiles, roles=("main", "critic", "judge"))
            rec = {r: _profile_to_dict(heur[r]) for r in heur} if heur else None
            source = "heuristic fallback (no model available to ask)"
        if not rec or not rec.get("main"):
            self.ui.warn("Could not produce a recommendation.")
            return
        self.ui.rule(f"suggested arrangement · via {source}")
        for role in ("main", "critic", "judge"):
            m = rec.get(role)
            if m:
                state = "loaded" if m.get("loaded") else "[yellow]not loaded[/yellow]"
                self.ui.console.print(f"  [bold]{role:7s}[/bold] → {m.get('display_name', m['key'])} "
                                      f"[grey58]({m.get('params', '')} {m.get('max_context_length', '?')} ctx)[/grey58] · {state}")
        if rec.get("reason"):
            self.ui.info(f"  reason: {rec['reason']}")
        if rec.get("approach") and rec["approach"] not in ("", "single"):
            self.ui.info(f"  suggested approach: {rec['approach']}")
        if self.auto_approve or self._authorize("Apply this assignment (and load any missing models)?"):
            self._apply_recommendation(rec)

    def _llm_recommend(self, task: str, models: list[dict]) -> dict | None:
        """Ask a loaded model which model fits each role for this task.

        Returned keys are validated against the catalog; embeddings and
        hallucinated keys get corrected to a real chat model.
        """
        router = self._router_client()
        if router is None:
            return None
        catalog = [{"key": m["key"], "name": m.get("display_name", m["key"]),
                    "params": m.get("params", ""), "context": m.get("max_context_length"),
                    "type": m.get("type", "llm"), "vision": bool(m.get("vision")),
                    "loaded": bool(m.get("loaded"))} for m in models]
        router.max_tokens = 512
        user = f"TASK:\n{task}\n\nAVAILABLE MODELS (JSON):\n{json.dumps(catalog)}"
        try:
            turn = router.complete(prompts.MODEL_ROUTER_PROMPT, [{"role": "user", "content": user}], [])
        except Exception as e:  # noqa: BLE001
            self.ui.warn(f"  router model error: {str(e)[:120]}")
            return None
        data = orch.extract_json(turn.content) or {}
        by_key = {m["key"]: m for m in models}

        def is_chat(m: dict) -> bool:
            return (m.get("type") or "llm").lower() != "embeddings"

        def pick(role: str, exclude: set) -> dict | None:
            k = data.get(role)
            if k in by_key and is_chat(by_key[k]) and k not in exclude:
                return by_key[k]
            for m in models:  # a loaded chat model not already taken
                if m.get("loaded") and is_chat(m) and m["key"] not in exclude:
                    return m
            return by_key.get(self.client.model)

        main = pick("main", set())
        critic = pick("critic", {main["key"]} if main else set())
        judge = pick("judge", {m["key"] for m in (main, critic) if m})
        return {"main": main, "critic": critic, "judge": judge,
                "approach": str(data.get("approach", "")).lower(),
                "reason": str(data.get("reason", ""))[:300]}

    def _apply_recommendation(self, rec: dict) -> None:
        from code_agent.lmstudio import LMStudioManager
        mgr = LMStudioManager(self.lmstudio_url)
        try:
            for role in ("main", "critic", "judge"):
                m = rec.get(role)
                if m and not m.get("loaded"):
                    self.ui.info(f"  loading {m.get('display_name', m['key'])} … "
                                 f"[grey58](big models on CPU can take minutes; Ctrl+C to abort)[/grey58]")
                    r = mgr.load_model(m["key"])
                    if not r.get("success"):
                        self.ui.warn(f"    failed to load {m['key']}: {r.get('error')}")
        except KeyboardInterrupt:
            self.ui.warn("  load aborted.")
            return
        if rec.get("main"):
            self._select_main(rec["main"])
        if rec.get("critic"):
            self.critic_model = rec["critic"]["key"]
        if rec.get("judge"):
            self.judge_model = rec["judge"]["key"]
        self.ui.success("Applied. Verifying…")
        self.startup_preflight()

    def _router_client(self):
        """A throwaway client for routing/classification.

        Prefers a loaded local chat model so we don't pay the cloud for routing;
        falls back to the main client, else None.
        """
        for m in self._all_models():
            if (m.get("provider") != "claude" and m.get("loaded")
                    and not mp.profile(m).is_embedding):
                return self._own_client(m["key"])
        if self.registry is not None and (self.registry.has_claude() or self.registry.has_lmstudio()):
            return self.client.for_model(self.client.model)
        if self.client.name != "lmstudio":  # single-provider path (e.g. tests)
            return self.client.for_model(self.client.model)
        return None

    def _recent_task(self) -> str:
        for m in reversed(self.messages):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                return m["content"]
        return ""

    def _cmd_preflight(self, arg: str) -> None:
        self.startup_preflight(force=True)

    def startup_preflight(self, force: bool = False) -> None:
        """Ping each loaded chat model (1 token, parallel) for liveness + latency.

        Liveness only, not tool-use: LMStudio's tool-use flag under-reports.
        """
        models = self._loaded_models()
        if not models:
            if force:
                self.ui.warn("No loaded models to check.")
            return
        profiles = {m["key"]: mp.profile(m) for m in models}
        # Ping local chat models only. Cloud models are always ready (and a ping
        # costs an API call); embeddings can't chat.
        cloud = {m["key"] for m in models if m.get("provider") == "claude"}
        chat_keys = [k for k, p in profiles.items() if not p.is_embedding and k not in cloud]
        if not chat_keys and not force and not cloud:
            return
        self.ui.info(f"[preflight] pinging {len(chat_keys)} local chat model(s)…")
        try:
            results = {r[0]: r for r in self._preflight(chat_keys)}
        except KeyboardInterrupt:
            self.ui.warn("  preflight cancelled.")
            return
        for m in models:
            k, p = m["key"], profiles[m["key"]]
            if k in cloud:
                self.ui.success(f"  ✓ {p.display_name}: cloud (ready)")
                continue
            if p.is_embedding:
                self.ui.info(f"  · {p.display_name}: embedding model (skipped)")
                continue
            r = results.get(k)
            if not r or not r[1]:
                err = r[3] if r else "no result"
                self.ui.warn(f"  ✗ {p.display_name}: no response: {err}")
                continue
            latency = r[2]
            if latency > 20:
                self.ui.warn(f"  ✓ {p.display_name}: responds, but SLOW ({latency:.0f}s "
                             f"for 1 token, likely on CPU / heavily offloaded)")
            else:
                self.ui.success(f"  ✓ {p.display_name}: ok ({latency:.1f}s)")

    def _preflight(self, keys: list[str]) -> list:
        import time

        def ping(key: str):
            client = self._own_client(key)
            client.max_tokens = 1
            client.request_timeout = 90  # keep preflight from hanging
            t0 = time.perf_counter()
            try:
                client.complete("Reply with ok.", [{"role": "user", "content": "ping"}], [])
                return (key, True, time.perf_counter() - t0, "")
            except Exception as e:  # noqa: BLE001
                return (key, False, time.perf_counter() - t0, str(e)[:140])
        return orch.parallel([(lambda k=k: ping(k)) for k in keys], self.max_parallel_agents)

    def _cmd_review(self, arg: str) -> None:
        target, kind = self._review_target(arg)
        if not target:
            self.ui.info("Nothing to review (no plan, no recent diff, no git changes).")
            return
        critic = self._critic_spec()
        self.ui.info(f"[review] {critic.client.model} reviewing the {kind}…")
        res = orch.critic_review(target, kind, critic)
        self._print_verdict(res.structured or {}, res)

    def _cmd_panel(self, arg: str) -> None:
        task = arg.strip()
        if not task:
            self.ui.info("Usage: /panel <task>. Several models draft a plan, a judge picks/merges.")
            return
        proposers = self._proposer_specs()
        judge = self._judge_spec()
        # Several models loaded and no roles pinned: confirm the auto arrangement.
        if (self.client.name == "lmstudio" and len(self._loaded_models()) >= 2
                and not (self.critic_model or self.judge_model) and not self.auto_approve):
            self._show_arrangement(proposers, judge)
            ans = self._ask("Use this arrangement? (Y/n/assign)")
            if ans.startswith("n"):
                self.ui.info("Cancelled. Set roles with /assign, then rerun /panel.")
                return
            if ans.startswith("a"):
                self._assign_wizard()
                proposers = self._proposer_specs()
                judge = self._judge_spec()
        self._show_arrangement(proposers, judge)
        result = orch.judge_panel(task, proposers, judge, self.max_parallel_agents)
        if result["winner_index"] < 0:
            errs = {p.name: p.error for p in result["proposals"] if not p.ok}
            self.ui.error("All proposers failed.")
            for name, err in list(errs.items())[:3]:
                self.ui.console.print(f"    [red]{name}: {str(err)[:160]}[/red]")
            self.ui.info("Check /agents (are the models loaded?) and /assign to pick models.")
            return
        verdict = result.get("verdict") or {}
        for s in verdict.get("scores", []) or []:
            self.ui.console.print(f"  [grey58]proposal {s.get('index')}[/grey58] "
                                  f"score {s.get('score')}: {str(s.get('reason',''))[:100]}")
        self.ui.success(f"Winner: proposal {result['winner_index']}. Synthesized plan:")
        self.ui.console.print(result["synthesis"])
        self.current_plan = result["synthesis"]
        self.mode = "approve"
        self.ui.info("Approve this plan? (yes/no/revise)")

    def _cmd_investigate(self, arg: str) -> None:
        arg = arg.strip()
        if not arg:
            self.ui.info("Usage: /investigate <question>  or  /investigate <a>; <b>; <c>")
            return
        if ";" in arg:
            subtasks = [s.strip() for s in arg.split(";") if s.strip()]
        else:
            subtasks = self._decompose(arg)
        n = min(len(subtasks), self.max_parallel_agents)
        self.ui.info(f"[investigate] {len(subtasks)} area(s) across up to {n} parallel agents…")
        results = orch.parallel_investigate(
            subtasks, lambda st: self._explorer_spec(st), self.max_parallel_agents)
        combined = []
        for st, res in zip(subtasks, results):
            self.ui.rule(st[:60])
            if res.error:
                self.ui.error(f"  {res.error}")
                continue
            self.ui.console.print(res.text.strip() or "(no findings)")
            combined.append(f"### {st}\n{res.text.strip()}")
        if combined:
            self.messages.append({"role": "user",
                                  "content": "[Parallel investigation findings]\n\n" + "\n\n".join(combined)})
            self.ui.info("Findings added to context. Continue your request and I'll use them.")

    def _cmd_build(self, arg: str) -> None:
        task = arg.strip()
        if not task:
            self.ui.info("Usage: /build <task>. Implement, then a supervising model reviews and drives fixes.")
            return
        self.recent_diffs = []
        self._append_user(task)
        system = self._active_system(prompts.CODING_SYSTEM_PROMPT)
        self._tool_loop(system, self.messages, self.tools_all)

        for attempt in range(2):  # at most 2 supervised fix rounds
            if not self.recent_diffs:
                break
            critic = self._critic_spec()
            self.ui.info(f"[build] {critic.client.model} reviewing the changes…")
            res = orch.critic_review("\n\n".join(self.recent_diffs), "diff", critic)
            verdict = res.structured or {}
            self._print_verdict(verdict, res)
            if verdict.get("verdict") == "approve":
                self.ui.success("[build] Reviewer approved. Done.")
                return
            issues = verdict.get("issues") or []
            if not issues:
                return
            self.recent_diffs = []
            fix_msg = "A reviewer found these issues, fix them:\n" + "\n".join(f"- {i}" for i in issues)
            self.messages.append({"role": "user", "content": fix_msg})
            self.ui.info("[build] Sending issues back to the implementer…")
            self._tool_loop(system, self.messages, self.tools_all)
        self.ui.info("[build] Fix rounds exhausted.")

    def _cmd_supervise(self, arg: str) -> None:
        self.supervise = arg.strip().lower() not in ("off", "false", "0", "no")
        self.ui.info(f"Supervise mode {'on' if self.supervise else 'off'}.")

    def _cmd_auto(self, arg: str) -> None:
        self.auto_orchestrate = arg.strip().lower() not in ("off", "false", "0", "no")
        self.ui.info(f"Auto-suggest {'on' if self.auto_orchestrate else 'off'}.")

    def _cmd_benchmark(self, arg: str) -> None:
        """Run the task-suite benchmark against the current main model.

        Spawns `python -m benchmark.harness.run` from the code-agent repo (the
        benchmark ships in the repo, not the wheel) and streams its output.
        Arguments pass through: /benchmark --levels 1-3 --trials 3, /benchmark
        oracle (short for --oracle), /benchmark --tasks L4-01.
        """
        import os
        import shlex
        import subprocess
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        if not (repo_root / "benchmark" / "harness" / "run.py").exists():
            self.ui.error("benchmark/ not found next to the package — it ships in the "
                          "code-agent repo. Clone the repo and `pip install -e \".[bench]\"`.")
            return
        try:
            args = shlex.split(arg)
        except ValueError as e:
            self.ui.error(f"Bad arguments: {e}")
            return
        if args and args[0] == "oracle":
            args[0] = "--oracle"
        oracle = "--oracle" in args
        if not oracle and self.client.name != "lmstudio":
            self.ui.warn("The benchmark drives the LM Studio backend, but the current "
                         "main model is Claude. Pick a local model first (/models, /model N).")
            return

        cmd = [sys.executable, "-m", "benchmark.harness.run", *args]
        if "--lmstudio-url" not in args:
            cmd += ["--lmstudio-url", self.lmstudio_url]
        env = {**os.environ, "AI_PROVIDER": "lmstudio"}
        if not oracle and self.client.model not in ("", "default", None):
            env["LMSTUDIO_MODEL"] = self.client.model

        self.ui.rule("benchmark")
        target = "oracle (reference patches)" if oracle else self.client.model
        self.ui.info(f"  model: {target}")
        self.ui.info(f"  results: {repo_root / 'benchmark' / 'results'}")
        proc = subprocess.Popen(cmd, cwd=repo_root, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            for line in proc.stdout:
                # markup=False: benchmark output contains literal brackets ("[1/18]")
                self.ui.console.print("  " + line.rstrip(), style="grey58", markup=False)
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            self.ui.warn("\n[benchmark cancelled]")
            return
        if proc.returncode == 0:
            self.ui.success("Benchmark finished.")
        else:
            self.ui.error(f"Benchmark exited with code {proc.returncode}.")

    # ── model discovery & role assignment ─────────────────────────────────

    def _all_models(self) -> list[dict]:
        """Every selectable model: Claude first (if configured), then LMStudio
        models loaded and not. Each dict carries a 'provider' key."""
        claude: list[dict] = []
        lm: list[dict] = []
        if self.registry is not None and self.registry.has_claude():
            claude = self.registry.claude_model_dicts()
        # Query LMStudio whenever a transport exists; the else-branch is the
        # single-provider path used by tests.
        want_lm = (self.registry.has_lmstudio() if self.registry is not None
                   else self.client.name == "lmstudio")
        if want_lm:
            try:
                from code_agent.lmstudio import LMStudioManager
                lm = LMStudioManager(self.lmstudio_url).list_models()
                for m in lm:
                    m.setdefault("provider", "lmstudio")
            except Exception:
                lm = []
        return claude + lm

    def _is_cloud(self, key: str) -> bool:
        return self.registry is not None and self.registry.is_claude(key)

    def _loaded_models(self) -> list[dict]:
        """Currently-loaded models, all types, for display."""
        return [m for m in self._all_models() if m.get("loaded")]

    def _chat_models(self) -> list[dict]:
        """Loaded models usable as chat agents (no embeddings)."""
        return [m for m in self._loaded_models() if not mp.profile(m).is_embedding]

    def _chat_keys(self) -> list[str]:
        return [m["key"] for m in self._chat_models()]

    def _auto_chat_keys(self) -> list[str]:
        """Chat models eligible for automatic role assignment.

        Kept to the main model's provider so auto never spends on the cloud;
        mix providers by hand with /assign or /model.
        """
        main_is_cloud = self._is_cloud(self.client.model)
        return [m["key"] for m in self._chat_models()
                if (m.get("provider") == "claude") == main_is_cloud]

    def _eff_role(self, explicit: str, exclude: set) -> tuple[str, bool]:
        """Resolve a role's model as (model_key, was_auto_assigned).

        A pinned model wins (any provider). Otherwise pick a loaded chat model
        not in `exclude`, preferring the main provider, and fall back to the main
        model when there's only one. Never an embedding.
        """
        if explicit:
            return explicit, False
        for key in self._auto_chat_keys():
            if key not in exclude:
                return key, True
        return self.client.model, False

    def _eff_critic(self) -> str:
        return self._eff_role(self.critic_model, {self.client.model})[0]

    def _eff_judge(self) -> str:
        return self._eff_role(self.judge_model, {self.client.model, self._eff_critic()})[0]

    def _client_for(self, model: str):
        if not model or model == self.client.model:
            return self.client
        if self.registry is not None:
            try:
                return self.registry.client_for(model)
            except Exception:
                pass
        return self.client.for_model(model)

    def _own_client(self, model: str):
        """A fresh client for `model` so temperature tweaks stay isolated."""
        try:
            return self._client_for(model).for_model(model)
        except Exception:
            return self._client_for(model)

    def _role_prompt(self, template: str) -> str:
        return prompts.render(template, workdir=self.workdir, rules=self.rules)

    def _critic_spec(self) -> "orch.AgentSpec":
        client = self._client_for(self._eff_critic())
        return orch.AgentSpec(name="critic", client=client,
                              system_prompt=self._role_prompt(prompts.CRITIC_PROMPT),
                              tools=orch.read_only_tools_for(client), workdir=self.workdir, max_rounds=8)

    def _judge_spec(self) -> "orch.AgentSpec":
        client = self._own_client(self._eff_judge())
        client.temperature = 0.0
        return orch.AgentSpec(name="judge", client=client,
                              system_prompt=prompts.JUDGE_PROMPT, tools=[], workdir=self.workdir, max_rounds=2)

    def _explorer_spec(self, subtask: str) -> "orch.AgentSpec":
        client = self.client
        return orch.AgentSpec(name=f"explore:{subtask[:20]}", client=client,
                              system_prompt=self._role_prompt(prompts.EXPLORER_PROMPT),
                              tools=orch.read_only_tools_for(client), workdir=self.workdir, max_rounds=8)

    def _panel_models(self) -> list[str]:
        """Which model each proposer runs on.

        Pinned roles first, then all loaded models (real MoE), then just the main
        model padded with copies.
        """
        if self.critic_model or self.judge_model:
            models = [self.client.model]
            for m in (self._eff_critic(), self._eff_judge()):
                if m not in models:
                    models.append(m)
        else:
            loaded = self._auto_chat_keys()
            models = loaded[:self.max_parallel_agents] if len(loaded) >= 2 else [self.client.model]
        if len(models) < 2:  # one model: pad with copies for temperature diversity
            models = (models * min(3, self.max_parallel_agents))[:min(3, self.max_parallel_agents)]
        return models[:self.max_parallel_agents]

    def _proposer_specs(self) -> list:
        specs = []
        for i, model in enumerate(self._panel_models()):
            client = self._own_client(model)
            client.temperature = min(0.9, 0.4 + 0.2 * i)
            specs.append(orch.AgentSpec(name=f"proposer{i}:{model}", client=client,
                                        system_prompt=self._role_prompt(prompts.PROPOSER_PROMPT),
                                        tools=orch.read_only_tools_for(client), workdir=self.workdir, max_rounds=8))
        return specs

    # ── arrangement display & manual assignment ───────────────────────────

    def _show_arrangement(self, proposers: list, judge) -> None:
        models = ", ".join(p.client.model for p in proposers)
        self.ui.console.print(f"  [grey58]arrangement:[/grey58] {len(proposers)} proposer(s) "
                              f"[[cyan]{models}[/cyan]] → judge [[cyan]{judge.client.model}[/cyan]]")

    def _cmd_assign(self, arg: str) -> None:
        parts = arg.split()
        loaded = self._loaded_models()
        if not loaded:
            self.ui.info("Assignment needs available models (loaded local models or Claude). See /agents.")
            return
        if len(parts) != 2 or parts[0] not in ("main", "critic", "judge") or not parts[1].isdigit():
            self.ui.info("Usage: /assign main|critic|judge <number>  (numbers from /agents)")
            return
        role, idx = parts[0], int(parts[1]) - 1
        if not (0 <= idx < len(loaded)):
            self.ui.warn("Invalid model number (see /agents).")
            return
        self._set_role(role, loaded[idx])
        self.ui.success(f"{role} → {loaded[idx]['display_name']}")

    def _set_role(self, role: str, model: dict) -> None:
        if role == "critic":
            self.critic_model = model["key"]
        elif role == "judge":
            self.judge_model = model["key"]
        elif role == "main":
            self._select_main(model)

    def _assign_wizard(self) -> None:
        loaded = self._loaded_models()
        if not loaded:
            return
        self.ui.info("Loaded models:")
        for i, m in enumerate(loaded, 1):
            self.ui.console.print(f"   {i:2d}. {m['display_name']} [grey58]({m['max_context_length']:,} ctx)[/grey58]")
        for role, current in (("main", self.client.model), ("critic", self._eff_critic()),
                              ("judge", self._eff_judge())):
            ans = self._ask(f"{role} model [{current}] (number or blank to keep)")
            if ans.isdigit() and 0 <= int(ans) - 1 < len(loaded):
                self._set_role(role, loaded[int(ans) - 1])

    def _ask(self, question: str) -> str:
        try:
            return input(f"  \033[93m{question}:\033[0m ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return ""

    def _decompose(self, task: str) -> list[str]:
        """Split a broad task into 2-4 independent investigation subtasks."""
        sys = ("Split the user's request into 2-4 INDEPENDENT investigation subtasks that can run "
               "in parallel. Respond with ONLY a JSON array of strings.")
        try:
            turn = self.client.complete(sys, [{"role": "user", "content": task}], [])
            import json as _json
            data = _json.loads((turn.content or "").strip())
            subs = [str(x) for x in data if str(x).strip()]
            return subs[:4] or [task]
        except Exception:
            return [task]

    def _supervise_plan(self) -> None:
        if not self.current_plan:
            return
        critic = self._critic_spec()
        self.ui.info(f"[supervise] {critic.client.model} reviewing the plan…")
        res = orch.critic_review(self.current_plan, "plan", critic)
        self._print_verdict(res.structured or {}, res)

    def _supervise_diff(self) -> None:
        critic = self._critic_spec()
        self.ui.info(f"[supervise] {critic.client.model} reviewing the changes…")
        res = orch.critic_review("\n\n".join(self.recent_diffs), "diff", critic)
        self._print_verdict(res.structured or {}, res)

    def _print_verdict(self, verdict: dict, res) -> None:
        v = (verdict.get("verdict") or "revise").lower()
        color = {"approve": "green", "revise": "yellow", "reject": "red"}.get(v, "yellow")
        self.ui.console.print(f"  verdict: [{color}]{v.upper()}[/{color}]: {verdict.get('summary', '')}")
        for issue in verdict.get("issues", []) or []:
            self.ui.console.print(f"    [yellow]•[/yellow] {issue}")

    def _maybe_suggest(self, user_input: str) -> bool:
        """Classify and, when useful, execute the initial auto-v2 route."""
        if not self.auto_orchestrate or self.mode == "approve":
            return False
        decision = self._classify_approach(user_input)
        selected = decision.approach
        if selected != "single" and decision.confidence < AUTO_ROUTE_CONFIDENCE:
            decision.signals.append("below-confidence-threshold")
            selected = "single"
        effective = 1 if selected == "single" else min(
            decision.parallelism, self.max_parallel_agents)
        event = {"phase": "initial", **asdict(decision), "selected": selected,
                 "effective_parallelism": effective, "executed": False}
        self._routing["events"].append(event)
        self.ui.info(f"[{AUTO_POLICY_VERSION}] route={selected} "
                     f"confidence={decision.confidence:.2f} parallelism={effective}"
                     + (f" — {decision.reason}" if decision.reason else ""))
        if selected not in ("investigate", "panel"):
            return False
        label = {"investigate": "parallel investigation",
                 "panel": "a multi-model plan panel"}[selected]
        detail = f" ({decision.reason})" if decision.reason else ""
        if not self._authorize(f"A model suggests {label} for this{detail}. Run it?"):
            event["declined"] = True
            return False
        previous = self.max_parallel_agents
        self.max_parallel_agents = effective
        try:
            (self._cmd_investigate if selected == "investigate" else self._cmd_panel)(user_input)
        finally:
            self.max_parallel_agents = previous
        event["executed"] = True
        event["models"] = self._routing_models(selected, effective)
        return True

    def _classify_approach(self, task: str) -> RouteDecision:
        """Ask a loaded model for a validated, structured route decision."""
        router = self._router_client()
        if router is None:
            return RouteDecision(reason="no router model available")
        router.max_tokens = 300
        try:
            turn = router.complete(prompts.APPROACH_CLASSIFIER_PROMPT,
                                   [{"role": "user", "content": task}], [])
        except Exception as exc:
            return RouteDecision(reason=f"router error: {str(exc)[:100]}")
        data = orch.extract_json(turn.content) or {}
        approach = str(data.get("approach", "single")).lower()
        if approach not in {"single", "investigate", "panel"}:
            approach = "single"
        try:
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        try:
            parallelism = max(1, min(self.max_parallel_agents,
                                     int(data.get("parallelism", 1))))
        except (TypeError, ValueError):
            parallelism = 1
        if approach == "single":
            parallelism = 1
        raw_signals = data.get("signals") or []
        if not isinstance(raw_signals, list):
            raw_signals = [raw_signals]
        signals = [str(x)[:80] for x in raw_signals if str(x).strip()][:6]
        return RouteDecision(approach, confidence, parallelism, signals,
                             str(data.get("reason", ""))[:160])

    def routing_summary(self) -> dict:
        """Machine-readable route evidence for one-shot callers and benchmarks."""
        return json.loads(json.dumps(self._routing))

    def _routing_models(self, approach: str, parallelism: int) -> list[str]:
        if approach == "panel":
            return self._panel_models()[:parallelism]
        if approach == "investigate":
            keys = self._auto_chat_keys() or [self.client.model]
            return [keys[i % len(keys)] for i in range(parallelism)]
        return [self.client.model]

    def _authorize(self, question: str) -> bool:
        if self.auto_approve:
            return True
        try:
            ans = input(f"  \033[93m{question} (y/N):\033[0m ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return False
        return ans in ("y", "yes")

    def _review_target(self, arg: str):
        from pathlib import Path
        arg = arg.strip()
        if arg:
            p = Path(self.workdir) / arg
            if p.is_file():
                return p.read_text(encoding="utf-8", errors="replace"), f"file {arg}"
        if self.current_plan:
            return self.current_plan, "plan"
        if self.recent_diffs:
            return "\n\n".join(self.recent_diffs), "diff"
        out = json.loads(self.executor.execute("run_command", {"command": "git diff"}))
        diff = (out.get("stdout") or "").strip()
        if diff:
            return diff, "git diff"
        return None, ""

    # ── mode handlers ─────────────────────────────────────────────────────

    def _handle_plan(self, user_input: str) -> None:
        if not self.memory.goal:
            self.memory.set_goal(user_input)
        self._append_user(user_input)
        system = self._active_system(prompts.PLAN_PHASE_PROMPT)
        self.current_plan = self._tool_loop(system, self.messages, self.tools_plan, capture_plan=True)
        if _looks_like_plan(self.current_plan):
            self.mode = "approve"
            if self.supervise:
                self._supervise_plan()
            if self.auto_approve:
                self.ui.info("[auto-approve] executing plan…")
                self._handle_approval("yes")
        elif self.current_plan:
            self.ui.warn("[Plan not finalized] The model asked a question or was interrupted.")
            self.ui.info("Reply to keep planning, or /direct to execute without a plan.")
            self.current_plan = None

    def _handle_approval(self, user_input: str) -> None:
        stripped = user_input.strip()
        first = stripped.split(None, 1)[0].lower() if stripped else ""
        extra = stripped[len(first):].lstrip(" ,.;:-")

        if first in ("yes", "y", "approve", "approved", "go"):
            self.ui.success("Plan approved. Executing…")
            if extra:
                self.ui.info(f"Extra guidance: {extra}")
            if self.current_plan:
                self.memory.set_plan(self.current_plan)
            system = self._active_system(prompts.EXECUTE_PHASE_PROMPT, plan=self.current_plan or "")
            self.messages = []  # start execution with fresh context
            msg = f"Execute the following approved plan:\n\n{self.current_plan}"
            if extra:
                msg += f"\n\nAdditional instructions from the user:\n{extra}"
            self.messages.append({"role": "user", "content": msg})
            self.recent_diffs = []
            self._tool_loop(system, self.messages, self.tools_all)
            if self.supervise and self.recent_diffs:
                self._supervise_diff()
            self.mode = "direct"
            if self.plan_mode:
                self.ui.info("[Execute finished] Switched to direct mode. Type /plan for a new feature.")
            self.current_plan = None
        elif first in ("no", "n", "cancel", "discard"):
            self.ui.info("Plan discarded. Back to plan mode.")
            self.mode = "plan" if self.plan_mode else "direct"
            self.current_plan = None
        else:
            self.ui.warn("Treating as revision feedback. (Start with 'yes' to approve or 'no' to discard.)")
            self._append_user(f"Please revise the plan based on this feedback: {user_input}")
            system = self._active_system(prompts.PLAN_PHASE_PROMPT)
            self.current_plan = self._tool_loop(system, self.messages, self.tools_plan, capture_plan=True)

    def _handle_direct(self, user_input: str) -> None:
        self.recent_diffs = []
        self._auto_runtime = {"verification_failures": 0, "localization_errors": 0,
                              "stalled": False}
        self._append_user(user_input)
        system = self._active_system(prompts.CODING_SYSTEM_PROMPT)
        self._tool_loop(system, self.messages, self.tools_all)
        self._auto_runtime_escalate(user_input, system)

    def _auto_runtime_escalate(self, task: str, system: str) -> None:
        """Apply bounded recovery routes when the direct loop produces evidence it needs help."""
        if not self.auto_orchestrate:
            return
        needs_investigation = (self._auto_runtime["stalled"]
                               or self._auto_runtime["localization_errors"] >= 2)
        if needs_investigation and self._authorize(
                "The direct loop stalled while locating the change. Run a parallel investigation?"):
            parallelism = min(3, self.max_parallel_agents)
            event = {"phase": "runtime", "selected": "investigate",
                     "reason": "direct-loop stall or repeated localization errors",
                     "effective_parallelism": parallelism, "executed": True,
                     "models": self._routing_models("investigate", parallelism)}
            self._routing["events"].append(event)
            previous = self.max_parallel_agents
            self.max_parallel_agents = parallelism
            try:
                self._cmd_investigate(task)
            finally:
                self.max_parallel_agents = previous
            self.messages.append({"role": "user", "content": (
                "Use the investigation findings to recover from the stalled attempt. "
                "Finish the original task and verify the result.")})
            self._auto_runtime["stalled"] = False
            self._tool_loop(system, self.messages, self.tools_all)

        if (self._auto_runtime["verification_failures"] >= 2 and self.recent_diffs
                and self._authorize("Verification failed repeatedly. Run a critic review?")):
            critic = self._critic_spec()
            self.ui.info(f"[{AUTO_POLICY_VERSION}] runtime route=review — repeated verification failures")
            res = orch.critic_review("\n\n".join(self.recent_diffs), "diff", critic)
            verdict = res.structured or {}
            self._print_verdict(verdict, res)
            event = {"phase": "runtime", "selected": "review",
                     "reason": "two or more failed verification commands",
                     "effective_parallelism": 1, "executed": True,
                     "models": [critic.client.model],
                     "verdict": str(verdict.get("verdict", "unknown"))}
            self._routing["events"].append(event)
            issues = verdict.get("issues") or []
            if verdict.get("verdict") in {"revise", "reject"} and issues:
                self.messages.append({"role": "user", "content":
                    "A runtime reviewer found these issues; fix and verify them:\n" +
                    "\n".join(f"- {issue}" for issue in issues)})
                self._tool_loop(system, self.messages, self.tools_all)

    def _append_user(self, text: str) -> None:
        augmented, attached = expand_file_mentions(text, self.workdir)
        if attached:
            self.ui.info(f"  attached: {', '.join(attached)}")
        self.messages.append({"role": "user", "content": augmented})

    # ── the agentic tool loop ─────────────────────────────────────────────

    def _tool_loop(self, system_prompt: str, messages: list[dict],
                   tools: list[dict], capture_plan: bool = False) -> str | None:
        last_text: str | None = None
        last_tool_call = None
        repeat_count = 0
        rounds_since_progress = 0
        last_meta_check = 0
        empty_nudges = 0

        while True:
            if self._over_context(messages):
                break

            stream_cb = self.ui.assistant_stream() if self.stream else None
            try:
                if self.stream:
                    turn = self.client.stream(system_prompt, messages, tools, on_text=stream_cb)
                else:
                    turn = self.client.complete(system_prompt, messages, tools)
            except KeyboardInterrupt:
                if stream_cb:
                    stream_cb.end()
                self.ui.warn("\n[interrupted]")
                break
            except Exception as e:
                if self._handle_api_error(e, messages):
                    continue
                break

            streamed = stream_cb.end() if stream_cb else ""
            text = turn.content or streamed or None
            if text:
                last_text = text
                if not streamed:  # nothing streamed, so render it now
                    self.ui.assistant_text(text)
                self.tracker.record_request(messages, text)

            self.ui.status_line(self.tracker.format_status())

            if not turn.tool_calls:
                self.client.append_assistant(messages, turn)
                # Weak local models sometimes emit their "tool call" as XML text
                # inside the reasoning channel; the API then hands us an empty
                # message with no tool calls. Don't accept that as completion.
                if not (text and text.strip()) and empty_nudges < 2:
                    empty_nudges += 1
                    self.ui.warn("[empty response] nudging the model to continue…")
                    messages.append({"role": "user", "content": (
                        "Your last message was empty. If you intended to call a tool, "
                        "emit it as a structured tool call — never write the call as "
                        "text or inside your reasoning. Continue working on the task; "
                        "if it is fully complete, reply with a brief summary instead.")})
                    continue
                break

            # Guard against repeat loops by comparing the first tool call.
            sig = (turn.tool_calls[0]["function"]["name"], turn.tool_calls[0]["function"]["arguments"])
            if sig == last_tool_call:
                repeat_count += 1
                if repeat_count >= 3:
                    self.ui.warn("[Warning] Model repeating the same action. Stopping.")
                    self._auto_runtime["stalled"] = True
                    self._final_nudge(system_prompt, messages, tools)
                    break
            else:
                repeat_count = 0
            last_tool_call = sig

            self.client.append_assistant(messages, turn)
            self._execute_tools(turn.tool_calls, messages)

            # stall self-check
            round_tools = {tc["function"]["name"] for tc in turn.tool_calls}
            if round_tools & PROGRESS_TOOL_NAMES:
                rounds_since_progress = 0
                last_meta_check = 0
            else:
                rounds_since_progress += 1
                if (rounds_since_progress >= CYCLE_SOFT_CHECK_ROUNDS
                        and rounds_since_progress - last_meta_check >= CYCLE_SOFT_CHECK_INTERVAL):
                    last_meta_check = rounds_since_progress
                    if self._self_check(system_prompt, messages, tools):
                        break

        return last_text if capture_plan else None

    def _execute_tools(self, tool_calls: list[dict], messages: list[dict]) -> None:
        results: list[tuple[str, str, str]] = []
        interrupted = False
        for tc in tool_calls:
            name = tc["function"]["name"]
            tc_id = tc.get("id") or f"call_{name}"
            args_str = tc["function"]["arguments"]
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
            except Exception:
                args = {}
            if interrupted:
                results.append((tc_id, name, json.dumps({"error": "skipped: user interrupted"})))
                continue
            self.ui.tool_call(name, args)
            # dispatch_agents is intercepted here; it's authorized separately and
            # never hits the executor.
            if name == "dispatch_agents":
                results.append((tc_id, name, self._run_dispatch_agents(args)))
                continue
            try:
                result = self.executor.execute(name, args)
            except KeyboardInterrupt:
                self.ui.warn("  [interrupted mid-tool]")
                result = json.dumps({"error": "interrupted by user"})
                interrupted = True
            self._observe_auto_tool_result(name, args, result)
            results.append((tc_id, name, result))
            if self.executor.last_display:
                self.ui.diff(self.executor.last_display)
                if self.executor.last_display.get("diff"):
                    self.recent_diffs.append(self.executor.last_display["diff"])
                    self.recent_diffs = self.recent_diffs[-40:]
            else:
                self.ui.tool_result(name, result)
        self.client.append_tool_results(messages, results)

    def _observe_auto_tool_result(self, name: str, args: dict, result: str) -> None:
        if not self.auto_orchestrate:
            return
        try:
            data = json.loads(result)
        except (TypeError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        if name in {"read_file", "search_files", "list_files"} and data.get("error"):
            self._auto_runtime["localization_errors"] += 1
        if name != "run_command" or not data.get("exit_code"):
            return
        command = str(args.get("command", "")).lower()
        verification_markers = (
            "pytest", "unittest", "npm test", "npm run test", "npm run build",
            "pnpm test", "yarn test", "cargo test", "cargo check", "dotnet test",
            "ruff", "mypy", "pyright", "tsc", "gradle test", "mvn test",
        )
        if any(marker in command for marker in verification_markers):
            self._auto_runtime["verification_failures"] += 1

    def _run_dispatch_agents(self, args: dict) -> str:
        """Handle a dispatch_agents call: authorize, then fan out read-only agents."""
        tasks = args.get("tasks") or []
        tasks = [str(t).strip() for t in tasks if str(t).strip()][:self.max_parallel_agents]
        if not tasks:
            return json.dumps({"error": "no tasks provided"})
        self.ui.info(f"  model wants to spawn {len(tasks)} read-only agent(s):")
        for t in tasks:
            self.ui.console.print(f"    [grey58]- {t[:100]}[/grey58]")
        if not self._authorize("Authorize spawning these agents?"):
            return json.dumps({"status": "declined by user"})
        results = orch.parallel_investigate(
            tasks, lambda st: self._explorer_spec(st), self.max_parallel_agents)
        findings = []
        for t, r in zip(tasks, results):
            findings.append({"task": t, "findings": (r.text or r.error or "")[:4000]})
            self.ui.rule(t[:60])
            self.ui.console.print((r.text or r.error or "").strip()[:1000])
        return json.dumps({"agents": findings})

    # ── context management ───────────────────────────────────────────────

    def _over_context(self, messages: list[dict]) -> bool:
        t = self.tracker
        t.record_request(messages)
        if t.usage_percent > 85:
            old = t.used_tokens
            result = self._compact(messages)
            if result is not None:
                messages[:], _ = result
                t.record_request(messages)
                self.ui.info(f"[Context] Auto-compacted, freed ~{max(0, old - t.used_tokens):,} tokens "
                             f"({t.usage_percent:.0f}% used)")
        if t.usage_percent > 80:
            old_count = len(messages)
            messages[:] = trim_messages_to_fit(messages, t.context_window, t.system_tokens)
            if len(messages) < old_count:
                self.ui.info(f"[Context] Trimmed {old_count - len(messages)} old messages "
                             f"({t.usage_percent:.0f}% used)")
                t.record_request(messages)
        if t.usage_percent > 95:
            self.ui.error(f"[Context Full] {t.format_compact()}. Use /compact or clear.")
            return True
        return False

    def _handle_api_error(self, e: Exception, messages: list[dict]) -> bool:
        """Return True to retry the loop, False to break."""
        s = str(e).lower()
        if any(k in s for k in ("context", "token", "length")):
            self.ui.error("[Context Overflow] Trimming and retrying…")
            messages[:] = trim_messages_to_fit(
                messages, self.tracker.context_window, self.tracker.system_tokens, keep_recent=6)
            self.tracker.record_request(messages)
            return True
        self.ui.error(f"[AI Error] {e}")
        return False

    def _compact(self, messages: list[dict], keep_recent_user_turns: int = 1):
        cut = _find_compaction_cut_index(messages, keep_recent_user_turns)
        if cut < 2:
            return None
        transcript = _render_messages_for_summary(messages[:cut])
        if not transcript.strip():
            return None
        try:
            turn = self.client.complete(prompts.COMPACT_SYSTEM_PROMPT,
                                        [{"role": "user", "content": transcript}], [])
        except Exception:
            return None
        summary = (turn.content or "").strip()
        if not summary:
            return None
        summary_msg = {"role": "user", "content": f"[Conversation compacted to save context]\n\n{summary}"}
        return ([summary_msg] + messages[cut:], summary)

    # ── stall handling ───────────────────────────────────────────────────

    def _self_check(self, system_prompt: str, messages: list[dict], tools: list[dict]) -> bool:
        """Ask the model to self-assess; True means stop the loop."""
        self.ui.info("[Self-check] several rounds without a write/edit/memory; asking the model…")
        probe = messages + [{"role": "user", "content": prompts.META_CHECK_PROMPT}]
        try:
            turn = self.client.complete(system_prompt, probe, [])
        except Exception:
            return False
        text = (turn.content or "").strip()
        first_line = text.lower().splitlines()[0] if text else ""
        status = ("stuck" if "stuck" in first_line or "status: stuck" in text.lower()
                  else "progressing" if "progressing" in first_line or "status: progressing" in text.lower()
                  else "unclear")
        preview = (text.splitlines()[0] if text else "(no response)")[:200]

        if status == "stuck":
            self.ui.warn(f"Model says STUCK: {preview}")
            self._auto_runtime["stalled"] = True
            messages.append({"role": "user", "content": prompts.META_CHECK_PROMPT})
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": prompts.STUCK_FOLLOWUP})
            self._final_nudge(system_prompt, messages, tools)
            return True
        if status == "progressing":
            self.ui.success(f"Model says PROGRESSING: {preview}")
            messages.append({"role": "user", "content": prompts.META_CHECK_PROMPT})
            messages.append({"role": "assistant", "content": text})
            return False
        self.ui.info("Model response unclear, continuing.")
        return False

    def _final_nudge(self, system_prompt: str, messages: list[dict], tools: list[dict]) -> None:
        """One last blocking turn so the model can wrap up cleanly."""
        messages.append({"role": "user",
                         "content": "Summarize what you've accomplished and give your final response."})
        try:
            turn = self.client.complete(system_prompt, messages, [])
            if turn.content:
                self.ui.assistant_text(turn.content)
                messages.append({"role": "assistant", "content": turn.content})
        except Exception:
            pass


# ── module helpers (pure) ─────────────────────────────────────────────

def _profile_to_dict(p) -> dict:
    """Convert a ModelProfile to the model-dict shape _apply_recommendation wants."""
    return {"key": p.key, "display_name": p.display_name, "params": f"{p.params_b:g}B" if p.params_b else "",
            "max_context_length": p.context, "loaded": p.loaded}


def _looks_like_plan(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return "ready to execute" in lowered or "execute this plan" in lowered


def _find_compaction_cut_index(messages: list[dict], keep_recent_user_turns: int = 1) -> int:
    user_turns = [i for i, m in enumerate(messages)
                  if m.get("role") == "user" and isinstance(m.get("content"), str)]
    if len(user_turns) <= keep_recent_user_turns:
        return 0
    return user_turns[-keep_recent_user_turns]


def _render_messages_for_summary(messages: list[dict]) -> str:
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, str) and content:
            snippet = content if len(content) <= 1500 else content[:1500] + " …[truncated]"
            lines.append(f"[{role}] {snippet}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    text = block.get("content") or block.get("text") or ""
                    if not isinstance(text, str):
                        text = json.dumps(text)
                    snippet = text if len(text) <= 800 else text[:800] + " …[truncated]"
                    lines.append(f"[{role}/tool_result] {snippet}")
        for tc in m.get("tool_calls", []) or []:
            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
            args = fn.get("arguments", "")
            if not isinstance(args, str):
                args = json.dumps(args)
            args = args if len(args) <= 300 else args[:300] + " …"
            lines.append(f"[{role}/tool_call] {fn.get('name', '?')}({args})")
    return "\n".join(lines)
