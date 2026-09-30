"""Runs the coding tool calls: file I/O and shell commands.

edit_file is deliberately forgiving (local models often get whitespace slightly
wrong): exact match, then whitespace-tolerant, then a "did you mean" snippet.
"""

from __future__ import annotations

import difflib
import fnmatch
import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from code_agent.coder.browser_tools import BrowserSession
from code_agent.coder.session_memory import SessionMemory
from code_agent.coder.web_tools import github_read, web_fetch, web_search

# Dirs we skip when searching/listing.
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
              ".pytest_cache", ".ruff_cache", "dist", "build", ".idea", ".tox"}


class CodingToolExecutor:
    def __init__(self, workdir: str, memory: SessionMemory | None = None) -> None:
        self._workdir = Path(workdir).resolve()
        self._memory = memory
        # Set after a write/edit for the UI to render; the model only sees the JSON return.
        self.last_display: dict | None = None
        self._browser_worker: ThreadPoolExecutor | None = None
        self._browser: BrowserSession | None = None

    def execute(self, tool_name: str, arguments: dict) -> str:
        self.last_display = None
        handler = getattr(self, f"_handle_{tool_name}", None)
        if handler is None:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        try:
            result = handler(**arguments)
            return json.dumps(result, default=str)
        except TypeError as e:
            # Usually a bad or missing argument from the model.
            return json.dumps({"error": f"Invalid arguments for {tool_name}: {e}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _resolve(self, path: str) -> Path:
        """Resolve a path relative to workdir, refusing escapes."""
        resolved = (self._workdir / path).resolve()
        if resolved != self._workdir and self._workdir not in resolved.parents:
            raise ValueError(f"Path escapes working directory: {path}")
        return resolved

    def _rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self._workdir))
        except ValueError:
            return str(p)

    # ── File operations ───────────────────────────────────────────────

    def _handle_read_file(
        self, path: str, start_line: int | None = None, end_line: int | None = None
    ) -> dict:
        filepath = self._resolve(path)
        if not filepath.is_file():
            return {"error": f"File not found: {path}"}

        raw = filepath.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        total = len(lines)

        start = max(0, (start_line or 1) - 1)
        end = end_line or total
        selected = lines[start:end]

        # Don't dump a huge file into context all at once.
        MAX_LINES = 800
        note = None
        if start_line is None and end_line is None and total > MAX_LINES:
            selected = lines[:MAX_LINES]
            end = MAX_LINES
            note = (
                f"File has {total} lines; showing first {MAX_LINES}. "
                f"Use start_line/end_line to read a specific range."
            )

        numbered = [f"{i + start + 1:5d} | {line}" for i, line in enumerate(selected)]
        out = {
            "path": path,
            "total_lines": total,
            "showing": f"{start + 1}-{min(end, total)}",
            "content": "\n".join(numbered),
        }
        if note:
            out["note"] = note
        return out

    def _handle_write_file(self, path: str, content: str) -> dict:
        filepath = self._resolve(path)
        is_new = not filepath.exists()
        old = "" if is_new else filepath.read_text(encoding="utf-8", errors="replace")

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")

        lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        if self._memory:
            (self._memory.record_file_created if is_new else self._memory.record_file_modified)(path)

        self.last_display = {
            "kind": "create" if is_new else "overwrite",
            "path": path,
            "diff": _unified_diff(old, content, path),
        }
        return {"path": path, "written": True, "created": is_new, "lines": lines}

    def _handle_edit_file(
        self, path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> dict:
        filepath = self._resolve(path)
        if not filepath.is_file():
            return {"error": f"File not found: {path}. Use write_file to create it."}
        if old_string == new_string:
            return {"error": "old_string and new_string are identical; nothing to change."}

        text = filepath.read_text(encoding="utf-8", errors="replace")

        new_text, applied, detail = _apply_edit(text, old_string, new_string, replace_all)
        if new_text is None:
            hint = _closest_snippet(text, old_string)
            err: dict = {
                "error": f"old_string not found in {path}. {detail}",
                "advice": "Read the file again to copy the exact text (including indentation), then retry.",
            }
            if hint:
                err["did_you_mean"] = hint
            return err

        filepath.write_text(new_text, encoding="utf-8")
        if self._memory:
            self._memory.record_file_modified(path)

        self.last_display = {
            "kind": "edit",
            "path": path,
            "diff": _unified_diff(text, new_text, path),
        }
        return {"path": path, "edited": True, "replacements": applied, "match": detail}

    # ── Directory operations ──────────────────────────────────────────

    def _handle_list_files(self, path: str = ".", pattern: str | None = None) -> dict:
        dirpath = self._resolve(path)
        if not dirpath.is_dir():
            return {"error": f"Not a directory: {path}"}

        entries: list[str] = []
        if pattern:
            for match in sorted(dirpath.rglob(pattern)):
                if any(part in _SKIP_DIRS for part in match.parts):
                    continue
                suffix = "/" if match.is_dir() else ""
                entries.append(f"{self._rel(match)}{suffix}")
        else:
            for item in sorted(dirpath.iterdir()):
                if item.name in _SKIP_DIRS:
                    continue
                suffix = "/" if item.is_dir() else ""
                entries.append(f"{self._rel(item)}{suffix}")

        truncated = len(entries) > 300
        entries = entries[:300]
        return {"path": path, "count": len(entries), "truncated": truncated, "entries": entries}

    def _handle_search_files(
        self, pattern: str, path: str = ".", file_pattern: str | None = None
    ) -> dict:
        dirpath = self._resolve(path)
        rg = shutil.which("rg")
        if rg:
            result = self._search_ripgrep(rg, pattern, dirpath, file_pattern)
            if result is not None:
                return result
        return self._search_python(pattern, dirpath, file_pattern)

    # ── Public internet (authorization is enforced by CoderSession) ──

    def _handle_web_search(self, query: str, max_results: int = 5) -> dict:
        return web_search(query, max_results=max_results)

    def _handle_web_fetch(self, url: str, max_chars: int = 12000) -> dict:
        return web_fetch(url, max_chars=max_chars)

    def _handle_github_read(
        self, owner: str, repo: str, path: str = "", ref: str = "",
    ) -> dict:
        return github_read(owner, repo, path=path, ref=ref)

    # ── Isolated public browser ────────────────────────────────────────

    def _browser_call(self, method: str, **kwargs) -> dict:
        if self._browser_worker is None:
            self._browser_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="code-agent-browser")
        def invoke() -> dict:
            if self._browser is None:
                self._browser = BrowserSession()
            return getattr(self._browser, method)(**kwargs)
        return self._browser_worker.submit(invoke).result(timeout=60)

    def _handle_browser_open(self, url: str) -> dict:
        return self._browser_call("open", url=url)

    def _handle_browser_snapshot(self, max_chars: int = 12000) -> dict:
        return self._browser_call("snapshot", max_chars=max_chars)

    def _handle_browser_fill(self, target: str, value: str, by: str = "label") -> dict:
        return self._browser_call("fill", target=target, value=value, by=by)

    def _handle_browser_click(self, target: str, by: str = "role", role: str = "button") -> dict:
        return self._browser_call("click", target=target, by=by, role=role)

    def _handle_browser_close(self) -> dict:
        return self._browser_call("close")

    def close(self) -> None:
        if self._browser_worker is not None:
            try:
                if self._browser is not None:
                    self._browser_worker.submit(self._browser.close).result(timeout=15)
            finally:
                self._browser_worker.shutdown(wait=False, cancel_futures=True)
                self._browser_worker = None
                self._browser = None

    def _search_ripgrep(
        self, rg: str, pattern: str, dirpath: Path, file_pattern: str | None
    ) -> dict | None:
        max_matches = 200
        cmd = [rg, "--json", "--hidden", "--no-ignore", "--max-count", "50",
               "-i", "-e", pattern]
        if file_pattern:
            cmd += ["--glob", file_pattern]
        for skipped in sorted(_SKIP_DIRS):
            cmd += ["--glob", f"!**/{skipped}/**"]
        cmd.append(".")
        try:
            proc = subprocess.run(cmd, cwd=dirpath, capture_output=True, text=True, timeout=30)
        except Exception:
            return None
        # rg exits 1 on no matches, which is a valid empty result.
        if proc.returncode not in (0, 1):
            return None
        matches: list[dict] = []
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "match":
                continue
            data = event.get("data", {})
            fpath = data.get("path", {}).get("text", "")
            text = data.get("lines", {}).get("text", "")
            matches.append({"file": self._rel(Path(fpath)),
                            "line": int(data.get("line_number") or 0),
                            "text": text.strip()[:200]})
            if len(matches) >= max_matches:
                return {"count": len(matches), "truncated": True, "matches": matches, "engine": "ripgrep"}
        return {"count": len(matches), "truncated": False, "matches": matches, "engine": "ripgrep"}

    def _search_python(self, pattern: str, dirpath: Path, file_pattern: str | None) -> dict:
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return {"error": f"Invalid regex: {e}"}
        matches: list[dict] = []
        max_matches = 200
        for root, dirs, files in os.walk(str(dirpath)):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
            for fname in files:
                if file_pattern and not fnmatch.fnmatch(fname, file_pattern):
                    continue
                fpath = Path(root) / fname
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        matches.append({"file": self._rel(fpath), "line": i,
                                        "text": line.strip()[:200]})
                        if len(matches) >= max_matches:
                            return {"count": len(matches), "truncated": True,
                                    "matches": matches, "engine": "python"}
        return {"count": len(matches), "truncated": False, "matches": matches, "engine": "python"}

    # ── Shell ─────────────────────────────────────────────────────────

    def _handle_run_command(self, command: str, timeout: int = 120) -> dict:
        try:
            result = subprocess.run(
                command, shell=True, cwd=str(self._workdir),
                capture_output=True, text=True, timeout=timeout,
            )
            return {
                "exit_code": result.returncode,
                "stdout": (result.stdout or "")[:10000],
                "stderr": (result.stderr or "")[:5000],
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Command timed out after {timeout}s", "exit_code": -1}

    def _handle_install_package(self, package: str) -> dict:
        import sys

        cmd = f'"{sys.executable}" -m pip install {package}'
        try:
            result = subprocess.run(
                cmd, shell=True, cwd=str(self._workdir),
                capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired:
            return {"error": "Install timed out after 300s", "package": package}

        stdout = (result.stdout or "")[:5000]
        stderr = (result.stderr or "")[:3000]
        if result.returncode == 0:
            return {"success": True, "package": package, "stdout": stdout}
        return {"success": False, "package": package,
                "error": stderr or stdout, "exit_code": result.returncode}

    def _handle_update_memory(
        self, current_step: str = "", completed_step: str = "",
        decision: str = "", error: str = "",
    ) -> dict:
        if not self._memory:
            return {"status": "no memory available"}
        if completed_step:
            self._memory.complete_step(completed_step)
        if current_step:
            self._memory.set_current_step(current_step)
        if decision:
            self._memory.record_decision(decision)
        if error:
            self._memory.record_error(error)
        return {
            "status": "memory updated",
            "completed_steps": len(self._memory.completed_steps),
            "files_created": len(self._memory.files_created),
            "files_modified": len(self._memory.files_modified),
        }


# ── Edit matching helpers ─────────────────────────────────────────────

def _apply_edit(
    text: str, old: str, new: str, replace_all: bool
) -> tuple[str | None, int, str]:
    """Return (new_text, replacements, detail); (None, 0, reason) on no match.

    Exact match first, then whitespace-tolerant.
    """
    # Exact
    count = text.count(old)
    if count == 1:
        return text.replace(old, new, 1), 1, "exact"
    if count > 1:
        if replace_all:
            return text.replace(old, new), count, "exact (all occurrences)"
        return None, 0, f"found {count} exact matches; set replace_all=true or add surrounding context to target one."

    # Whitespace-tolerant (trailing spaces, CRLF, surrounding blank lines)
    window = _fuzzy_line_window(text, old)
    if window is not None:
        i, j = window
        file_lines = text.split("\n")
        new_lines = new.split("\n")
        rebuilt = file_lines[:i] + new_lines + file_lines[j:]
        return "\n".join(rebuilt), 1, "whitespace-tolerant"

    return None, 0, "no exact or whitespace-tolerant match found."


def _fuzzy_line_window(text: str, old: str) -> tuple[int, int] | None:
    """Unique contiguous line window matching `old` ignoring trailing whitespace/CRLF.

    Returns (start, end) or None. Leading indentation is not ignored; silently
    re-indenting is riskier than making the model retry.
    """
    def norm(lines: list[str]) -> list[str]:
        return [ln.rstrip() for ln in lines]

    file_lines = text.split("\n")
    old_lines = old.split("\n")
    # Trim blank lines off both ends of the needle.
    while old_lines and old_lines[0].strip() == "":
        old_lines = old_lines[1:]
    while old_lines and old_lines[-1].strip() == "":
        old_lines = old_lines[:-1]
    n = len(old_lines)
    if n == 0:
        return None

    old_norm = norm(old_lines)
    file_norm = norm(file_lines)
    hits = [i for i in range(0, len(file_norm) - n + 1) if file_norm[i:i + n] == old_norm]
    if len(hits) == 1:
        return hits[0], hits[0] + n
    return None


def _closest_snippet(text: str, old: str, threshold: float = 0.6) -> str | None:
    """Return the file region most similar to `old`, to help the model retry."""
    file_lines = text.split("\n")
    old_lines = [ln for ln in old.split("\n") if ln.strip()]
    n = max(1, len(old_lines))
    best_ratio = 0.0
    best_i = 0
    sm = difflib.SequenceMatcher()
    sm.set_seq2("\n".join(old_lines))
    for i in range(0, max(1, len(file_lines) - n + 1)):
        window = "\n".join(file_lines[i:i + n])
        sm.set_seq1(window)
        r = sm.quick_ratio()
        if r > best_ratio:
            best_ratio, best_i = r, i
    if best_ratio < threshold:
        return None
    start = max(0, best_i)
    end = min(len(file_lines), best_i + n)
    numbered = [f"{k + 1:5d} | {file_lines[k]}" for k in range(start, end)]
    return "\n".join(numbered)


def _unified_diff(old: str, new: str, path: str) -> str:
    """Compact unified diff between old and new content."""
    diff = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="", n=2,
    )
    return "\n".join(diff)
