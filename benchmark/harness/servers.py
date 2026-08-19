"""Serving a trial's app (API + built frontend) for browser/schema grading."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .procutil import kill_tree, popen_group_kwargs


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class AppServer:
    """uvicorn subprocess serving the trial backend plus frontend/dist statically."""

    def __init__(self, trial_dir: Path, db_path: Path, seed: bool = True,
                 log_path: Path | None = None):
        self.trial_dir = trial_dir
        self.db_path = db_path
        self.seed = seed
        self.log_path = log_path
        self.port = free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None
        self._log_file = None

    def start(self, timeout: float = 30.0) -> None:
        if self.db_path.exists():
            self.db_path.unlink()
        env = {
            **os.environ,
            "KANBAN_DB": str(self.db_path),
            "KANBAN_SEED": "1" if self.seed else "0",
            "KANBAN_STATIC": str(self.trial_dir / "frontend" / "dist"),
        }
        if self.log_path is not None:
            self._log_file = open(self.log_path, "a")
            out = err = self._log_file
        else:
            out = err = subprocess.DEVNULL
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--app-dir", str(self.trial_dir / "backend"),
             "--port", str(self.port), "--log-level", "warning"],
            env=env, stdout=out, stderr=err, **popen_group_kwargs(),
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{self.base_url}/api/boards", timeout=2.0).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if self.proc.poll() is not None:
                raise RuntimeError(f"app server exited early (code {self.proc.returncode})")
            time.sleep(0.3)
        self.stop()
        raise RuntimeError("app server did not become healthy in time")

    def stop(self) -> None:
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None
        if self.proc is None:
            return
        kill_tree(self.proc)

    def __enter__(self) -> "AppServer":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
