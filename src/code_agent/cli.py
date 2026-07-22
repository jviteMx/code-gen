"""CLI entry point for code-agent."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="code-agent",
        description="Local coding assistant (Claude Code-like) for Claude or LMStudio backend.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the working directory (default: current dir). "
        "Use 'configure' to run the setup wizard.",
    )
    parser.add_argument(
        "--provider",
        choices=["claude", "lmstudio"],
        default=None,
        help="AI provider to use (default: from config)",
    )
    parser.add_argument("--prompt", default=None, help="Initial prompt/instruction to start with")
    parser.add_argument("--no-plan", action="store_true", help="Skip plan mode and execute directly")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming output")
    parser.add_argument("--yes", action="store_true", help="Auto-approve plans (skip the approval prompt)")
    parser.add_argument(
        "--context",
        type=int,
        default=None,
        help="Override context window size in tokens (e.g. --context 32768)",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="Deprecated (kept for compatibility); context window is the real limit.",
    )
    # orchestration
    parser.add_argument("--supervise", action="store_true",
                        help="Auto-review every plan and diff with a 2nd model")
    parser.add_argument("--auto", action="store_true",
                        help="Let a model suggest an orchestration approach per task (off by default)")
    parser.add_argument("--no-preflight", action="store_true",
                        help="Skip the startup health-check ping of loaded models")
    parser.add_argument("--timeout", type=float, default=None,
                        help="Per-request timeout in seconds (default 600; backstop against hangs)")
    parser.add_argument("--max-parallel", type=int, default=None,
                        help="Max parallel sub-agents (match your LMStudio limit; default 5)")
    parser.add_argument("--critic-model", default=None, help="Model key for the critic/reviewer agent")
    parser.add_argument("--judge-model", default=None, help="Model key for the judge agent")

    args = parser.parse_args()

    if args.path == "configure":
        from code_agent.config import run_configure
        run_configure()
        return

    from code_agent.config import load_config
    config = load_config(cli_overrides={"ai_provider": args.provider} if args.provider else None)

    # Auto-fallback: if provider is claude but no API key, switch to lmstudio
    provider = config.ai_provider
    if provider == "claude" and not config.anthropic_api_key:
        print("  No Anthropic API key found. Falling back to LMStudio.\n")
        provider = "lmstudio"

    from code_agent.coder.loop import run_coding_session
    run_coding_session(
        workdir=args.path,
        context=args.prompt or "",
        lmstudio_url=config.lmstudio_url,
        lmstudio_model=config.lmstudio_model,
        anthropic_api_key=config.anthropic_api_key,
        anthropic_model=config.anthropic_model,
        provider=provider,
        plan_mode=not args.no_plan,
        context_override=args.context,
        max_rounds_override=args.max_rounds,
        stream=not args.no_stream,
        auto_approve=args.yes,
        max_parallel_agents=args.max_parallel or int(config.max_parallel_agents or 5),
        critic_model=args.critic_model if args.critic_model is not None else config.critic_model,
        judge_model=args.judge_model if args.judge_model is not None else config.judge_model,
        supervise=args.supervise,
        auto_orchestrate=args.auto,
        preflight=not args.no_preflight,
        request_timeout=args.timeout if args.timeout is not None else float(config.request_timeout or 600),
    )


if __name__ == "__main__":
    main()
