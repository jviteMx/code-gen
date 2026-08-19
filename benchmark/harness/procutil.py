"""Cross-platform subprocess helpers (the harness must run on Windows and POSIX)."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess


def popen_group_kwargs() -> dict:
    """Popen kwargs that put the child in its own killable process group/tree."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(proc: subprocess.Popen, term_timeout: float = 10.0) -> None:
    """Terminate a process and all its children (uvicorn workers, npm, node…)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
        try:
            proc.wait(timeout=term_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=term_timeout)
    except (subprocess.TimeoutExpired, ProcessLookupError):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


def npm_bin() -> str:
    """Resolve npm to a full path (on Windows the .cmd shim needs resolving)."""
    return shutil.which("npm") or "npm"
