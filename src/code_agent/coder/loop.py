"""Wires up the clients, UI, executor, memory, and tracker, then runs a CoderSession.

run_coding_session is the public entry point used by the CLI and by jt start.
"""

from __future__ import annotations

import os
from pathlib import Path

from openai import OpenAI

from code_agent.coder.coding_tools import CODING_TOOLS
from code_agent.coder.llm import AnthropicClient, ClientRegistry, OpenAIClient
from code_agent.coder.prompts import CODING_SYSTEM_PROMPT, render
from code_agent.coder.rules import load_all_rules, load_global_rules, load_project_rules
from code_agent.coder.session import CoderSession
from code_agent.coder.session_memory import SessionMemory
from code_agent.coder.token_counter import (
    TokenTracker, get_loaded_model_info, get_model_context_size,
)
from code_agent.coder.tool_executor import CodingToolExecutor
from code_agent.coder.ui import ReplUI

HISTORY_PATH = Path.home() / ".config" / "code-agent" / "history"


def run_coding_session(
    workdir: str,
    context: str = "",
    lmstudio_url: str = "http://localhost:1234/v1",
    lmstudio_model: str = "default",
    anthropic_api_key: str | None = None,
    anthropic_model: str = "claude-sonnet-4-20250514",
    provider: str = "lmstudio",
    plan_mode: bool = True,
    context_override: int | None = None,
    max_rounds_override: int | None = None,  # kept for CLI compat, unused
    temperature: float = 0.2,
    stream: bool = True,
    auto_approve: bool = False,
    max_parallel_agents: int = 5,
    critic_model: str = "",
    judge_model: str = "",
    supervise: bool = False,
    auto_orchestrate: bool = False,
    preflight: bool = True,
    request_timeout: float = 600.0,
) -> None:
    """Run an interactive coding session."""
    workdir = str(Path(workdir).resolve())

    memory = SessionMemory(workdir)
    memory.load()
    executor = CodingToolExecutor(workdir, memory=memory)
    rules = load_all_rules(workdir)

    use_anthropic = provider == "claude"

    # Build both provider clients when their credentials/endpoints exist, so any
    # role (and /model selection) can mix Claude and local models no matter which
    # provider is the main one.
    anthropic_client = None
    if anthropic_api_key:
        try:
            import anthropic
            anthropic_client = AnthropicClient(
                anthropic.Anthropic(api_key=anthropic_api_key), model=anthropic_model,
                temperature=temperature, request_timeout=request_timeout)
        except Exception as e:
            if use_anthropic:
                print(f"  [Error] Failed to initialize Claude: {e}")
                return
            print(f"  [warn] Claude unavailable ({e}); continuing without it.")

    normalized_url = lmstudio_url.rstrip("/")
    if not normalized_url.endswith("/v1"):
        normalized_url += "/v1"
    lmstudio_client = OpenAIClient(
        OpenAI(base_url=normalized_url, api_key="lm-studio"), model=lmstudio_model,
        temperature=temperature, request_timeout=request_timeout)

    model_info = None
    if use_anthropic:
        if anthropic_client is None:
            print("  [Error] Claude provider selected but no API key found.")
            return
        client = anthropic_client
        model_name = anthropic_model
    else:
        model_info = get_loaded_model_info(lmstudio_url)
        # "default"/empty isn't a routable key with several models loaded, so pick
        # a loaded chat model (never an embedding one).
        if lmstudio_model in ("", "default", None):
            resolved = _first_loaded_chat_model(lmstudio_url)
            if resolved:
                lmstudio_client.model = resolved
            elif model_info and model_info.get("key"):
                lmstudio_client.model = model_info["key"]
        client = lmstudio_client
        model_name = lmstudio_client.model

    registry = ClientRegistry(
        lmstudio=lmstudio_client, anthropic=anthropic_client,
        claude_models=[anthropic_model] if anthropic_client else [],
    )

    os.chdir(workdir)

    if context_override:
        ctx_size = context_override
    elif model_info and model_info.get("max_context_length"):
        ctx_size = model_info["max_context_length"]
    else:
        ctx_size = get_model_context_size(provider, model_name, lmstudio_url)

    tracker = TokenTracker(context_window=ctx_size)
    tracker.set_system_tokens(
        render(CODING_SYSTEM_PROMPT, workdir=workdir, rules=rules,
               context=context, memory=memory.format_for_prompt()),
        CODING_TOOLS,
    )

    ui = ReplUI(workdir, history_path=HISTORY_PATH)
    _print_banner(ui, workdir, provider, model_name, model_info, ctx_size, plan_mode, rules, memory, tracker)

    session = CoderSession(
        client=client, ui=ui, executor=executor, memory=memory, tracker=tracker,
        workdir=workdir, context=context, rules=rules, plan_mode=plan_mode,
        auto_approve=auto_approve, stream=stream, lmstudio_url=lmstudio_url,
        max_parallel_agents=max_parallel_agents, critic_model=critic_model,
        judge_model=judge_model, supervise=supervise, auto_orchestrate=auto_orchestrate,
        registry=registry,
    )
    loaded = session._loaded_models()
    if len(loaded) > 1:
        ui.info(f"  {len(loaded)} models loaded, roles auto-distribute across them. "
                f"/agents to see, /assign or /suggest to change.")
    if registry.has_claude() and registry.has_lmstudio():
        other = "local models" if use_anthropic else "Claude"
        ui.info(f"  Claude + local both available, so {other} shows in /models; "
                f"mix them with /model N or /assign main|critic|judge N.")
    if preflight:
        session.startup_preflight()
    try:
        session.run()
    except SystemExit:
        pass


def _first_loaded_chat_model(lmstudio_url: str) -> str | None:
    """First loaded LMStudio model that is not an embedding model, else None."""
    try:
        from code_agent.lmstudio import LMStudioManager
        from code_agent.coder import model_profiler as mp
        for m in LMStudioManager(lmstudio_url).list_models():
            if m.get("loaded") and not mp.profile(m).is_embedding:
                return m["key"]
    except Exception:
        pass
    return None


def _print_banner(ui, workdir, provider, model_name, model_info, ctx_size, plan_mode, rules, memory, tracker):
    c = ui.console
    ui.rule("Local Coding Assistant")
    c.print(f"  [grey58]dir[/grey58]   {workdir}")
    if model_info:
        c.print(f"  [grey58]model[/grey58] {model_info.get('display_name', model_name)}")
        details = " | ".join(filter(None, [
            model_info.get("params", ""), model_info.get("quantization", ""),
            model_info.get("architecture", ""),
        ]))
        if details:
            c.print(f"        [grey58]{details}[/grey58]")
        if model_info.get("tool_use"):
            c.print("        [green]tool use: supported[/green]")
    else:
        c.print(f"  [grey58]model[/grey58] {provider} ({model_name})")
    c.print(f"  [grey58]ctx[/grey58]   {ctx_size:,} tokens")
    c.print(f"  [grey58]mode[/grey58]  {'Plan → Execute' if plan_mode else 'Direct'}")
    if rules:
        if load_global_rules():
            c.print("  [grey58]rules[/grey58] global (~/.config/code-agent/rules.md)")
        if load_project_rules(workdir):
            c.print("  [grey58]rules[/grey58] project")
    if memory.goal:
        c.print(f"  [yellow]resuming:[/yellow] {memory.goal[:60]}… "
                f"({len(memory.completed_steps)} steps done)")
    ui.rule()
    ui.info("  Enter=send · Alt+Enter=newline · @path attaches a file · /help for commands")
    ui.status_line(tracker.format_status())
