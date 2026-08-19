"""OpenAPI conformance grading via schemathesis (one pass/fail F2P unit)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# not_a_server_error: no 5xx under fuzzing; response_schema_conformance:
# successful responses match the documented schema. Stricter checks
# (status_code_conformance, negative_data_rejection) fail on idiomatic
# FastAPI apps whose 4xx codes aren't all documented, so they'd punish
# correct solutions.
CHECKS = "not_a_server_error,response_schema_conformance"


def find_schemathesis_cli() -> str | None:
    """Find the console script beside the active Python, even if PATH is not activated."""
    on_path = shutil.which("schemathesis")
    if on_path:
        return on_path
    python_dir = Path(sys.executable).resolve().parent
    names = ["schemathesis.exe", "schemathesis"]
    candidates = [python_dir / name for name in names]
    candidates += [python_dir / "Scripts" / name for name in names]
    return next((str(path) for path in candidates if path.is_file()), None)


def run_schemathesis(base_url: str, out_dir: Path,
                     include_paths: list[str] | None = None,
                     max_examples: int = 30, seed: int = 0) -> tuple[bool, dict]:
    bin_path = find_schemathesis_cli()
    if bin_path is None:
        return False, {"error": "schemathesis CLI not found"}
    cmd = [
        bin_path, "run", f"{base_url}/openapi.json",
        "--checks", CHECKS,
        "--max-examples", str(max_examples),
        "--seed", str(seed),
        "--phases", "examples,coverage,fuzzing",
        "--wait-for-schema", "10",
    ]
    for path in include_paths or []:
        cmd += ["--include-path", path]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=600)
    (out_dir / "schemathesis.log").write_text(
        proc.stdout + "\n" + proc.stderr, encoding="utf-8"
    )
    return proc.returncode == 0, {"exit_code": proc.returncode}
