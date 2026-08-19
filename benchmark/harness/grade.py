"""Grading a finished trial: gates, P2P, F2P, localization, minimality."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .config import SUITES_DIR
from .procutil import npm_bin
from .schemas import Subscores, TaskSpec, weighted_score
from .servers import AppServer
from .workspace import diff_numstat, restore_paths

P2P_PROTECTED = "backend/tests/"
SOURCE_EXCLUDES = (P2P_PROTECTED, "backend/tests_f2p/")


def run_pytest(target: Path | str, cwd: Path, junit: Path,
               deselect: list[str] | None = None,
               env: dict | None = None) -> tuple[int, int]:
    """Run a pytest target; returns (passed, total) from the junit report."""
    cmd = [sys.executable, "-m", "pytest", str(target), "-q", "-p", "no:cacheprovider",
           f"--junitxml={junit}"]
    for node in deselect or []:
        cmd += ["--deselect", node]
    full_env = None
    if env:
        import os
        full_env = {**os.environ, **env}
    subprocess.run(cmd, cwd=cwd, capture_output=True, env=full_env)
    return parse_junit(junit)


def count_pytest_tests(target: Path | str, cwd: Path) -> int:
    """Collect pytest node IDs without executing fixtures or test bodies."""
    cmd = [sys.executable, "-m", "pytest", str(target), "--collect-only", "-q",
           "-p", "no:cacheprovider"]
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return 0
    # Quiet collection prints one fully-qualified node ID per test case. This
    # counts parametrized cases individually, matching the scoring contract.
    return sum(1 for line in proc.stdout.splitlines() if "::" in line)


def parse_junit(junit: Path) -> tuple[int, int]:
    """(passed, total) counting errors/failures as failed; skips excluded."""
    if not junit.exists():
        return (0, 0)
    try:
        root = ET.parse(junit).getroot()
    except ET.ParseError:
        return (0, 0)
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return (0, 0)
    tests = int(suite.get("tests", 0))
    failures = int(suite.get("failures", 0))
    errors = int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    total = tests - skipped
    return (max(0, total - failures - errors), total)


def gate_backend(trial: Path) -> bool:
    r = subprocess.run([sys.executable, "-m", "compileall", "-q", "backend/app"],
                       cwd=trial, capture_output=True)
    return r.returncode == 0


def gate_frontend_build(trial: Path) -> bool:
    r = subprocess.run([npm_bin(), "run", "build"], cwd=trial / "frontend",
                       capture_output=True, timeout=300)
    return r.returncode == 0


def inject_f2p(trial: Path, task: TaskSpec) -> Path | None:
    """Copy hidden backend F2P tests into the trial. Returns the injected dir."""
    src = task.dir / "f2p" / "backend"
    if not src.is_dir():
        return None
    dest = trial / "backend" / "tests_f2p"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir()
    for f in src.glob("*.py"):
        shutil.copy(f, dest / f.name)
    # The injected suite reuses the same fixtures as the committed P2P suite.
    shutil.copy(SUITES_DIR / "f2p_conftest.py", dest / "conftest.py")
    return dest


def localization_precision(modified: set[str], expected: set[str]) -> float:
    """Share of the agent's edits that stay inside the task's allowed footprint.

    expected_files is an allowlist, not a checklist: solutions that need fewer
    files than allowed aren't punished, edits outside the allowlist are.
    """
    if not expected:
        return 1.0
    if not modified:
        return 0.0
    return round(len(modified & expected) / len(modified), 4)


def reference_loc(patch_file: Path) -> int:
    loc = 0
    for line in patch_file.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\+[^+]", line) or re.match(r"^-[^-]", line):
            loc += 1
        elif line in ("+", "-"):
            loc += 1
    return loc


def source_files(numstat: list[tuple[int, int, str]]) -> set[str]:
    return {p for _, _, p in numstat if not any(p.startswith(x) for x in SOURCE_EXCLUDES)}


def grade(trial: Path, task: TaskSpec, baseline: str, out_dir: Path,
          schemathesis_runner=None) -> tuple[Subscores, bool, bool, dict]:
    """Grade the current state of a trial workspace.

    Returns (subscores, resolved, p2p_tampered, detail). Assumes the agent's
    work is already committed (snapshot); F2P tests are injected here, after
    the fact, so the agent can never have seen them.
    """
    detail: dict = {}
    sub = Subscores()

    numstat = diff_numstat(trial, baseline)

    # P2P suites are ground truth: revert any modification before running them.
    tampered_paths = [p for _, _, p in numstat if p.startswith(P2P_PROTECTED)]
    p2p_tampered = bool(tampered_paths)
    if p2p_tampered:
        restore_paths(trial, baseline, [P2P_PROTECTED.rstrip("/")])
        detail["p2p_tampered_files"] = tampered_paths

    # ── gate ──
    backend_ok = gate_backend(trial)
    frontend_ok = True
    if task.frontend:
        frontend_ok = gate_frontend_build(trial)
        sub.gate = (0.5 if backend_ok else 0.0) + (0.5 if frontend_ok else 0.0)
    else:
        sub.gate = 1.0 if backend_ok else 0.0
    detail["gate"] = {"backend_compile": backend_ok, "frontend_build": frontend_ok}

    # ── P2P ──
    p2p_passed, p2p_total = run_pytest("backend/tests", trial, out_dir / "junit_p2p.xml",
                                       deselect=task.p2p_ignore)
    backend_p2p = p2p_passed / p2p_total if p2p_total else 0.0
    detail["p2p_backend"] = {"passed": p2p_passed, "total": p2p_total}

    smoke_ratio = None
    needs_server = task.frontend or "playwright" in task.graders or "schemathesis" in task.graders

    # ── F2P backend units ──
    f2p_passed = f2p_total = 0
    if inject_f2p(trial, task) is not None:
        bp, bt = run_pytest("backend/tests_f2p", trial, out_dir / "junit_f2p.xml")
        f2p_passed, f2p_total = bp, bt
        detail["f2p_backend"] = {"passed": bp, "total": bt}

    # ── served-app grading (frontend smoke, playwright F2P, schemathesis) ──
    if needs_server and frontend_ok:
        # the grading DB must live on a native filesystem (trial dir), not under
        # results/ — SQLite on WSL2's 9p mount misbehaves under load
        server = AppServer(trial, db_path=trial / "grading.db",
                           log_path=out_dir / "server.log")
        try:
            server.start()
        except RuntimeError as e:
            detail["server_error"] = str(e)
            server = None
        if server is not None:
            try:
                env = {"BENCH_BASE_URL": server.base_url}
                if task.frontend:
                    sp, st = run_pytest(SUITES_DIR / "frontend_smoke", trial,
                                        out_dir / "junit_smoke.xml", env=env)
                    smoke_ratio = sp / st if st else 0.0
                    detail["p2p_smoke"] = {"passed": sp, "total": st}
                pw_dir = task.dir / "f2p" / "playwright"
                if pw_dir.is_dir():
                    # restart with a fresh DB so earlier suites can't leak state
                    server.stop()
                    server = AppServer(trial, db_path=trial / "grading.db",
                                       log_path=out_dir / "server.log")
                    server.start()
                    env = {"BENCH_BASE_URL": server.base_url}
                    pp, pt = run_pytest(pw_dir, trial, out_dir / "junit_f2p_pw.xml", env=env)
                    f2p_passed += pp
                    f2p_total += pt
                    detail["f2p_playwright"] = {"passed": pp, "total": pt}
                if "schemathesis" in task.graders and schemathesis_runner is not None:
                    ok, info = schemathesis_runner(
                        server.base_url, out_dir,
                        include_paths=task.schemathesis_paths,
                    )
                    if not ok:
                        # one retry on a fresh server+DB: a genuine contract bug
                        # fails again; a rare server flake passes and is flagged
                        first_log = out_dir / "schemathesis.log"
                        if first_log.exists():
                            first_log.rename(out_dir / "schemathesis.first-failure.log")
                        server.stop()
                        server = AppServer(trial, db_path=trial / "grading.db",
                                           log_path=out_dir / "server.log")
                        server.start()
                        ok, info = schemathesis_runner(
                            server.base_url, out_dir,
                            include_paths=task.schemathesis_paths,
                        )
                        info = {**info, "retried": True, "flaky": ok}
                    f2p_passed += 1 if ok else 0
                    f2p_total += 1
                    detail["schemathesis"] = info
            finally:
                server.stop()
    elif needs_server:
        detail["server_skipped"] = "frontend build failed"
        pw_dir = task.dir / "f2p" / "playwright"
        if pw_dir.is_dir():
            # The build prevented browser execution, but each collected
            # Playwright case still counts as a failed F2P unit.
            f2p_total += count_pytest_tests(pw_dir, trial)
        if "schemathesis" in task.graders:
            f2p_total += 1

    sub.f2p = f2p_passed / f2p_total if f2p_total else 0.0
    sub.p2p = backend_p2p if smoke_ratio is None else (backend_p2p + smoke_ratio) / 2

    # ── diff metrics ──
    modified = source_files(numstat)
    sub.localization = localization_precision(modified, set(task.expected_files))
    agent_loc = sum(a + r for a, r, p in numstat
                    if not any(p.startswith(x) for x in SOURCE_EXCLUDES))
    ref_patch = task.dir / "reference.patch"
    ref_loc = reference_loc(ref_patch) if ref_patch.exists() else 0
    if agent_loc <= 0:
        sub.minimality = 0.0
    elif ref_loc <= 0:
        sub.minimality = 1.0
    else:
        sub.minimality = round(min(1.0, ref_loc / agent_loc), 4)
    detail["diff"] = {"files": sorted(modified), "loc": agent_loc, "ref_loc": ref_loc}

    resolved = (f2p_total > 0 and f2p_passed == f2p_total
                and p2p_total > 0 and backend_p2p == 1.0
                and (smoke_ratio is None or smoke_ratio == 1.0))
    return sub, resolved, p2p_tampered, detail


def score(sub: Subscores, task: TaskSpec) -> float:
    return weighted_score(sub, task.effective_weights)
