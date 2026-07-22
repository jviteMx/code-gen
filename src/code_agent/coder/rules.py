"""Load and merge global + project rules for the coding assistant."""

from __future__ import annotations

from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "code-agent"
# global rules used to live under the jira-tool config dir
LEGACY_CONFIG_DIR = Path.home() / ".config" / "jira-tool"

# project rule files, first match wins
PROJECT_RULE_FILES = [
    "PROJECT.md",
    ".jt-rules",
    "JT.md",
]


def load_global_rules() -> str:
    """Global rules from ~/.config/code-agent/rules.md, falling back to the legacy jira-tool path."""
    for base in (CONFIG_DIR, LEGACY_CONFIG_DIR):
        rules_file = base / "rules.md"
        if rules_file.is_file():
            return rules_file.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def load_project_rules(workdir: str) -> str:
    """Nearest PROJECT.md / .jt-rules / JT.md walking up from workdir."""
    path = Path(workdir).resolve()

    for directory in [path, *path.parents]:
        for filename in PROJECT_RULE_FILES:
            candidate = directory / filename
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8", errors="replace").strip()
        # stop at the git root
        if (directory / ".git").exists():
            break

    return ""


def load_all_rules(workdir: str) -> str:
    """Load and merge global + project rules into a single string."""
    sections: list[str] = []

    global_rules = load_global_rules()
    if global_rules:
        sections.append(f"## Global Rules\n{global_rules}")

    project_rules = load_project_rules(workdir)
    if project_rules:
        sections.append(f"## Project Rules\n{project_rules}")

    if not sections:
        return ""

    return "\n\n".join(sections)
