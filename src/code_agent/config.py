"""Config loading: TOML file, environment, then CLI flags."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

# .env precedence: ./.env > ./.jt/.env > ~/.config/code-agent/.env
load_dotenv(find_dotenv(usecwd=True))
_jt_dir_env = Path.cwd() / ".jt" / ".env"
if _jt_dir_env.exists():
    load_dotenv(_jt_dir_env, override=False)
_home_env = Path.home() / ".config" / "code-agent" / ".env"
if _home_env.exists():
    load_dotenv(_home_env, override=False)

CONFIG_DIR = Path.home() / ".config" / "code-agent"
CONFIG_FILE = CONFIG_DIR / "config.toml"

# field name -> environment variable
ENV_MAP = {
    "ai_provider": "AI_PROVIDER",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "anthropic_model": "ANTHROPIC_MODEL",
    "lmstudio_url": "LMSTUDIO_URL",
    "lmstudio_model": "LMSTUDIO_MODEL",
    # orchestration
    "max_parallel_agents": "MAX_PARALLEL_AGENTS",
    "critic_model": "CRITIC_MODEL",
    "judge_model": "JUDGE_MODEL",
    "request_timeout": "REQUEST_TIMEOUT",
}


@dataclass
class Config:
    ai_provider: str = "claude"  # "claude" | "lmstudio"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    lmstudio_url: str = "http://localhost:1234/v1"
    lmstudio_model: str = "default"

    # max_parallel_agents should match LMStudio's parallel-request limit.
    # critic_model / judge_model default to the main model when empty; point them
    # at a different loaded model to have two models supervise each other.
    max_parallel_agents: str = "5"
    critic_model: str = ""
    judge_model: str = ""
    # Per-request timeout in seconds, so a hung/CPU-bound model can't block forever.
    request_timeout: str = "600"


def _parse_toml(path: Path) -> dict:
    """Parse a TOML file, returning an empty dict if missing."""
    if not path.exists():
        return {}
    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib  # type: ignore[no-redef]
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def load_config(cli_overrides: dict | None = None) -> Config:
    """Load config with priority: CLI flags > env vars > TOML file."""
    toml_data = _parse_toml(CONFIG_FILE)

    merged: dict[str, str] = {}

    for field_name in ENV_MAP:
        if field_name in toml_data:
            merged[field_name] = str(toml_data[field_name])

    for field_name, env_var in ENV_MAP.items():
        val = os.environ.get(env_var)
        if val:
            merged[field_name] = val

    if cli_overrides:
        for k, v in cli_overrides.items():
            if v is not None:
                merged[k] = v

    return Config(**{k: v for k, v in merged.items() if v})


def _write_toml(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f'{k} = "{v}"' for k, v in data.items()]
    CONFIG_FILE.write_text("\n".join(lines) + "\n")


def run_configure() -> None:
    """Interactive configuration wizard for the coding assistant."""
    print("=== code-agent configuration ===\n")

    existing = _parse_toml(CONFIG_FILE)

    def ask(prompt: str, key: str, secret: bool = False, default: str = "") -> str:
        current = existing.get(key, default)
        suffix = f" [{current}]" if current and not secret else ""
        if secret:
            val = getpass(f"{prompt}{suffix}: ") or current
        else:
            val = input(f"{prompt}{suffix}: ") or current
        return val

    data: dict[str, str] = {}

    print("-- AI Provider --")
    data["ai_provider"] = ask("AI provider (claude/lmstudio)", "ai_provider", default="claude")

    if data["ai_provider"] == "claude":
        data["anthropic_api_key"] = ask("Anthropic API key", "anthropic_api_key", secret=True)
        data["anthropic_model"] = ask("Claude model", "anthropic_model", default="claude-sonnet-4-20250514")
    else:
        data["lmstudio_url"] = ask("LMStudio URL", "lmstudio_url", default="http://localhost:1234/v1")
        data["lmstudio_model"] = ask("LMStudio model name", "lmstudio_model", default="default")

    _write_toml(data)
    print(f"\nConfig saved to {CONFIG_FILE}")
