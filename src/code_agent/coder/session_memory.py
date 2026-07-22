"""Persistent session state (goal, plan, progress) that survives context trims."""

from __future__ import annotations

import json
from pathlib import Path


class SessionMemory:
    """Session state, injected into the system prompt and persisted to disk."""

    def __init__(self, workdir: str) -> None:
        self.workdir = workdir
        self.goal: str = ""
        self.plan: str = ""
        self.completed_steps: list[str] = []
        self.current_step: str = ""
        self.files_modified: list[str] = []
        self.files_created: list[str] = []
        self.key_decisions: list[str] = []
        self.errors_encountered: list[str] = []

        self._memory_file = Path(workdir) / ".jt" / "session.json"

    def set_goal(self, goal: str) -> None:
        self.goal = goal
        self._save()

    def set_plan(self, plan: str) -> None:
        self.plan = plan
        self._save()

    def complete_step(self, step: str) -> None:
        self.completed_steps.append(step)
        self.current_step = ""
        self._save()

    def set_current_step(self, step: str) -> None:
        self.current_step = step
        self._save()

    def record_file_modified(self, path: str) -> None:
        if path not in self.files_modified:
            self.files_modified.append(path)
            self._save()

    def record_file_created(self, path: str) -> None:
        if path not in self.files_created:
            self.files_created.append(path)
            self._save()

    def record_decision(self, decision: str) -> None:
        self.key_decisions.append(decision)
        # Keep only last 10 decisions
        self.key_decisions = self.key_decisions[-10:]
        self._save()

    def record_error(self, error: str) -> None:
        self.errors_encountered.append(error)
        self.errors_encountered = self.errors_encountered[-5:]
        self._save()

    def update_from_tool_calls(self, tool_calls: list[dict], results: list[str]) -> None:
        """Auto-update memory based on tool calls and their results."""
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", "{}")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}

            if name == "write_file":
                path = args.get("path", "")
                if path:
                    self.record_file_created(path)
            elif name == "edit_file":
                path = args.get("path", "")
                if path:
                    self.record_file_modified(path)

    def format_for_prompt(self) -> str:
        """Format session memory as context for the system prompt."""
        if not self.goal and not self.completed_steps:
            return ""

        parts = ["## Session Memory (persistent across context trims)"]

        if self.goal:
            parts.append(f"### Goal\n{self.goal}")

        if self.plan:
            parts.append(f"### Approved Plan\n{self.plan}")

        if self.completed_steps:
            steps = "\n".join(f"  - [done] {s}" for s in self.completed_steps)
            parts.append(f"### Progress\n{steps}")

        if self.current_step:
            parts.append(f"### Currently Working On\n{self.current_step}")

        if self.files_created:
            parts.append(f"### Files Created\n" + ", ".join(self.files_created))

        if self.files_modified:
            parts.append(f"### Files Modified\n" + ", ".join(self.files_modified))

        if self.key_decisions:
            decisions = "\n".join(f"  - {d}" for d in self.key_decisions)
            parts.append(f"### Key Decisions\n{decisions}")

        if self.errors_encountered:
            errors = "\n".join(f"  - {e}" for e in self.errors_encountered)
            parts.append(f"### Errors Encountered\n{errors}")

        return "\n\n".join(parts)

    def clear(self) -> None:
        self.goal = ""
        self.plan = ""
        self.completed_steps = []
        self.current_step = ""
        self.files_modified = []
        self.files_created = []
        self.key_decisions = []
        self.errors_encountered = []
        if self._memory_file.exists():
            self._memory_file.unlink()

    def _save(self) -> None:
        try:
            self._memory_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "goal": self.goal,
                "plan": self.plan,
                "completed_steps": self.completed_steps,
                "current_step": self.current_step,
                "files_modified": self.files_modified,
                "files_created": self.files_created,
                "key_decisions": self.key_decisions,
                "errors_encountered": self.errors_encountered,
            }
            self._memory_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass  # non-critical

    def load(self) -> None:
        """Load previous session if it exists."""
        if not self._memory_file.exists():
            return
        try:
            data = json.loads(self._memory_file.read_text(encoding="utf-8"))
            self.goal = data.get("goal", "")
            self.plan = data.get("plan", "")
            self.completed_steps = data.get("completed_steps", [])
            self.current_step = data.get("current_step", "")
            self.files_modified = data.get("files_modified", [])
            self.files_created = data.get("files_created", [])
            self.key_decisions = data.get("key_decisions", [])
            self.errors_encountered = data.get("errors_encountered", [])
        except Exception:
            pass
