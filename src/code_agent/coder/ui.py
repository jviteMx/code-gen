"""Terminal UI: a prompt_toolkit input session plus rich rendering.

Handles Enter-to-send with Alt+Enter for newlines, bracketed paste, history,
slash-command and @path completion, and colored diffs/tables. Falls back to
plain stdin/stdout with no TTY.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

# imported lazily inside ReplUI so a non-TTY or import failure can fall back to input()

SLASH_COMMANDS = {
    "/plan": "switch to plan mode",
    "/direct": "switch to direct (no-plan) mode",
    "/init": "generate PROJECT.md from the codebase",
    "/compact": "summarize history to free context",
    "/tokens": "show token usage breakdown",
    "/memory": "show session memory",
    "/models": "list available models (local + Claude) by number",
    "/model": "set the main model by number; offers to unload the previous one; repeat on the current main to unload it (alias /load)",
    "/continue": "continue where the model left off",
    # multi-agent orchestration
    "/agents": "show agents, models, and orchestration status",
    "/assign": "assign a loaded model to a role: /assign main|critic|judge <n>",
    "/suggest": "ask a loaded model to pick the best models for the task; loads missing ones",
    "/preflight": "ping loaded models; report responsiveness + latency",
    "/review": "critic model reviews the current plan or recent diff",
    "/panel": "MoE: several models draft a plan, a judge picks/merges (/moe)",
    "/investigate": "fan out read-only explorer agents in parallel (/explore)",
    "/build": "implement → review → fix loop with a supervising model (/tdd)",
    "/supervise": "on|off: auto-review every plan and diff with a 2nd model",
    "/auto": "on|off: let the harness suggest an approach per task",
    "/benchmark": "benchmark the current model on the task suite (args pass through, e.g. /benchmark --levels 1-3 --trials 3; /bench)",
    "/clear": "clear conversation + memory",
    "/help": "show commands",
    "/quit": "end the session",
}


class ReplUI:
    def __init__(self, workdir: str, history_path: Path | None = None) -> None:
        self.workdir = Path(workdir).resolve()
        self.console = Console()
        self._status_provider = lambda: ""
        self._session = None
        self._pt = None
        self._build_session(history_path)

    # ── input ─────────────────────────────────────────────────────────

    def _build_session(self, history_path: Path | None) -> None:
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import FileHistory
            from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
            from prompt_toolkit.key_binding import KeyBindings
            import prompt_toolkit as pt

            if not sys.stdin.isatty():
                return  # piped input, use the plain fallback

            kb = KeyBindings()

            @kb.add("enter")
            def _(event):
                # pasted newlines come via bracketed paste and don't hit this binding
                event.current_buffer.validate_and_handle()

            @kb.add("escape", "enter")  # Alt+Enter → literal newline
            def _(event):
                event.current_buffer.insert_text("\n")

            hist = None
            if history_path is not None:
                history_path.parent.mkdir(parents=True, exist_ok=True)
                hist = FileHistory(str(history_path))

            self._pt = pt
            self._session = PromptSession(
                multiline=True,
                key_bindings=kb,
                history=hist,
                auto_suggest=AutoSuggestFromHistory(),
                completer=_MentionCompleter(self.workdir),
                complete_while_typing=False,
                bottom_toolbar=self._bottom_toolbar,
                mouse_support=False,
            )
        except Exception:
            self._session = None  # any setup failure falls back to input()

    def set_status_provider(self, fn) -> None:
        """fn() -> short status string for the bottom toolbar."""
        self._status_provider = fn

    def _bottom_toolbar(self):
        from prompt_toolkit.formatted_text import HTML

        try:
            status = self._status_provider() or ""
        except Exception:
            status = ""
        hint = "Enter=send · Alt+Enter=newline · @file to attach · /help"
        return HTML(f"<b>{_esc(status)}</b>  <style fg='#888888'>{_esc(hint)}</style>")

    def read(self, mode: str) -> str:
        """Read one message from the user. Raises EOFError/KeyboardInterrupt to quit."""
        label = {
            "plan": ("You [plan]", "#8be9fd"),
            "approve": ("Approve? (yes/no/revise)", "#f1fa8c"),
        }.get(mode, ("You", "#50fa7b"))

        if self._session is not None:
            from prompt_toolkit.formatted_text import HTML

            text = self._session.prompt(HTML(f"<b><style fg='{label[1]}'>{label[0]}:</style></b> "))
        else:
            # fallback: builtin input (single line)
            text = input(f"{label[0]}: ")
        return text.strip()

    # ── output ────────────────────────────────────────────────────────

    def banner(self, lines: list[str]) -> None:
        self.console.print()
        for ln in lines:
            self.console.print(ln)

    def rule(self, title: str = "") -> None:
        self.console.rule(title, style="grey37")

    def info(self, msg: str) -> None:
        self.console.print(f"[grey58]{msg}[/grey58]")

    def warn(self, msg: str) -> None:
        self.console.print(f"[yellow]{msg}[/yellow]")

    def error(self, msg: str) -> None:
        self.console.print(f"[bold red]{msg}[/bold red]")

    def success(self, msg: str) -> None:
        self.console.print(f"[green]{msg}[/green]")

    def status_line(self, text: str) -> None:
        # token_counter emits ANSI already; print raw so colors survive.
        self.console.print(f"  {text}", highlight=False)

    # Assistant streaming --------------------------------------------------

    def assistant_stream(self):
        """Return an on_text(piece) callback that renders a streamed reply. Call .end() when done."""
        return _AssistantStream(self.console)

    def assistant_text(self, text: str) -> None:
        if not text:
            return
        self.console.print()
        self.console.print(Text("Assistant: ", style="bold blue"), end="")
        self.console.print(text)

    # Tool activity --------------------------------------------------------

    def tool_call(self, name: str, args: dict) -> None:
        arg_str = json.dumps(args, ensure_ascii=False)
        if len(arg_str) > 160:
            arg_str = arg_str[:160] + "…"
        self.console.print(f"  [cyan]▶ {name}[/cyan] [grey58]{_rich_escape(arg_str)}[/grey58]")

    def tool_result(self, name: str, result_json: str) -> None:
        """Show a compact result for shell/install; diffs are shown separately."""
        try:
            r = json.loads(result_json)
        except Exception:
            return
        if isinstance(r, dict) and r.get("error"):
            self.console.print(f"    [red]{_rich_escape(str(r['error'])[:300])}[/red]")
            if r.get("did_you_mean"):
                self.console.print("    [grey58]did you mean:[/grey58]")
                for line in str(r["did_you_mean"]).splitlines()[:8]:
                    self.console.print(f"      [grey58]{_rich_escape(line)}[/grey58]")
            return
        if name in ("run_command", "install_package") and isinstance(r, dict):
            code = r.get("exit_code")
            if code is not None:
                color = "green" if code == 0 else "red"
                self.console.print(f"    [{color}]exit={code}[/{color}]")
            for line in (r.get("stdout") or "").splitlines()[:12]:
                self.console.print(f"    [grey70]{_rich_escape(line)}[/grey70]")
            err = (r.get("stderr") or "").strip()
            if err:
                for line in err.splitlines()[:6]:
                    self.console.print(f"    [red]{_rich_escape(line)}[/red]")

    def diff(self, display: dict) -> None:
        """Render a colored unified diff stashed by the executor."""
        kind = display.get("kind", "edit")
        path = display.get("path", "")
        label = {"create": "created", "overwrite": "rewrote", "edit": "edited"}.get(kind, "changed")
        diff_text = display.get("diff") or ""
        adds = sum(1 for line in diff_text.splitlines()
                   if line.startswith("+") and not line.startswith("+++"))
        dels = sum(1 for line in diff_text.splitlines()
                   if line.startswith("-") and not line.startswith("---"))
        self.console.print(f"    [green]{label}[/green] [bold]{_rich_escape(path)}[/bold] "
                           f"[green]+{adds}[/green] [red]-{dels}[/red]")
        shown = 0
        for line in diff_text.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                continue
            if shown >= 40:
                self.console.print("      [grey58]… diff truncated[/grey58]")
                break
            if line.startswith("+"):
                self.console.print(f"      [green]{_rich_escape(line)}[/green]")
            elif line.startswith("-"):
                self.console.print(f"      [red]{_rich_escape(line)}[/red]")
            elif line.startswith("@@"):
                self.console.print(f"      [cyan]{_rich_escape(line)}[/cyan]")
            else:
                self.console.print(f"      [grey50]{_rich_escape(line)}[/grey50]")
            shown += 1

    def models_table(self, models: list[dict]) -> None:
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("#", justify="right", style="grey58")
        table.add_column("Model")
        table.add_column("Params", style="grey70")
        table.add_column("Ctx", justify="right", style="grey70")
        table.add_column("", style="grey70")
        for i, m in enumerate(models, 1):
            status = "[green]LOADED[/green]" if m["loaded"] else ""
            tools = "🔧" if m.get("tool_use") else ""
            table.add_row(str(i), m["display_name"],
                          f"{m['params']} {m['quantization']}".strip(),
                          f"{m['max_context_length']:,}", f"{status} {tools}".strip())
        self.console.print(table)


class _AssistantStream:
    def __init__(self, console: Console) -> None:
        self._console = console
        self._started = False
        self._buf: list[str] = []

    def __call__(self, piece: str) -> None:
        if not piece:
            return
        if not self._started:
            self._console.print()
            self._console.print(Text("Assistant: ", style="bold blue"), end="")
            self._started = True
        self._buf.append(piece)
        sys.stdout.write(piece)
        sys.stdout.flush()

    def end(self) -> str:
        if self._started:
            sys.stdout.write("\n")
            sys.stdout.flush()
        return "".join(self._buf)


# ── @file mentions ────────────────────────────────────────────────────

def expand_file_mentions(text: str, workdir: str) -> tuple[str, list[str]]:
    """Append the contents of any @path mentions. Returns (augmented_text, attached_paths).

    Mentions that don't resolve to a file are left alone (they may just be prose).
    """
    import re

    root = Path(workdir).resolve()
    attached: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"(?:^|\s)@([^\s]+)", text):
        rel = m.group(1).rstrip(".,;:)")
        if rel in seen:
            continue
        candidate = (root / rel).resolve()
        if root != candidate and root not in candidate.parents:
            continue  # skip escapes outside the workdir
        if candidate.is_file():
            seen.add(rel)
            attached.append(rel)

    if not attached:
        return text, []

    sections = [text, "", "Referenced files:"]
    for rel in attached:
        try:
            content = (root / rel).read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if len(content) > 20000:
            content = content[:20000] + "\n… [truncated]"
        sections.append(f"\n=== {rel} ===\n{content}")
    return "\n".join(sections), attached


class _MentionCompleter:
    """Completes /slash commands and @file paths."""

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir

    def get_completions(self, document, complete_event):
        from prompt_toolkit.completion import Completion

        text = document.text_before_cursor
        word = text.split()[-1] if text.split() else ""

        if word.startswith("/"):
            for cmd, desc in SLASH_COMMANDS.items():
                if cmd.startswith(word):
                    yield Completion(cmd, start_position=-len(word), display_meta=desc)
            return

        if word.startswith("@"):
            frag = word[1:]
            base = self.workdir
            prefix = frag
            if "/" in frag:
                sub, prefix = frag.rsplit("/", 1)
                base = (self.workdir / sub)
            try:
                if base.is_dir():
                    for item in sorted(base.iterdir()):
                        if item.name in {".git", "node_modules", "__pycache__", ".venv"}:
                            continue
                        if item.name.startswith(prefix):
                            rel = item.relative_to(self.workdir)
                            suffix = "/" if item.is_dir() else ""
                            yield Completion(f"@{rel}{suffix}", start_position=-len(word),
                                             display=f"{rel}{suffix}")
            except Exception:
                return


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rich_escape(s: str) -> str:
    return s.replace("[", "\\[")
