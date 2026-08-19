"""Trial workspaces: template copies, node_modules cache, git baselines."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from .config import TEMPLATE_DIR
from .procutil import npm_bin

COPY_IGNORE = shutil.ignore_patterns(
    "node_modules", "dist", ".jt", "__pycache__", "*.pyc", "*.db", ".git"
)
DIFF_EXCLUDES = [":(exclude)node_modules", ":(exclude)dist", ":(exclude).jt",
                 ":(exclude)*.db", ":(exclude)*__pycache__*"]
GIT_ENV_ARGS = ["-c", "user.email=bench@local", "-c", "user.name=bench",
                "-c", "core.autocrlf=false"]


def _git(trial_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *GIT_ENV_ARGS, *args], cwd=trial_dir,
                          capture_output=True, text=True, check=check)


def ensure_node_modules_cache(scratch_root: Path) -> Path:
    """One `npm ci` per package-lock hash; trials hardlink from here."""
    frontend = TEMPLATE_DIR / "frontend"
    lock_hash = hashlib.sha256((frontend / "package-lock.json").read_bytes()).hexdigest()[:16]
    cache = scratch_root / "npm" / lock_hash
    marker = cache / ".complete"
    if marker.exists():
        return cache / "node_modules"
    cache.mkdir(parents=True, exist_ok=True)
    shutil.copy(frontend / "package.json", cache / "package.json")
    shutil.copy(frontend / "package-lock.json", cache / "package-lock.json")
    subprocess.run([npm_bin(), "ci", "--no-audit", "--no-fund"], cwd=cache, check=True,
                   capture_output=True)
    marker.touch()
    return cache / "node_modules"


def make_trial_dir(run_dir: Path, name: str, node_modules: Path | None) -> Path:
    trial = run_dir / name
    if trial.exists():
        shutil.rmtree(trial)
    shutil.copytree(TEMPLATE_DIR, trial, ignore=COPY_IGNORE)
    if node_modules is not None:
        # Hardlink farm: near-instant, and npm replaces files rather than editing
        # in place, so the shared cache cannot be corrupted from a trial.
        dest = trial / "frontend" / "node_modules"
        if os.name != "nt" and shutil.which("cp"):
            subprocess.run(["cp", "-al", str(node_modules), str(dest)], check=True)
        else:
            _link_tree(node_modules, dest)
    return trial


def _link_tree(src: Path, dest: Path) -> None:
    """Portable `cp -al`: hardlink files, recreate dirs/symlinks, copy on failure."""
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        (dest / rel).mkdir(parents=True, exist_ok=True)
        for name in files:
            s = Path(root) / name
            d = dest / rel / name
            if s.is_symlink():
                try:
                    os.symlink(os.readlink(s), d)
                    continue
                except OSError:
                    pass  # e.g. no symlink privilege on Windows — fall through
            try:
                os.link(s, d)
            except OSError:
                shutil.copy2(s, d)


def git_baseline(trial_dir: Path) -> str:
    _git(trial_dir, "init", "-q")
    _git(trial_dir, "add", "-A")
    _git(trial_dir, "commit", "-qm", "baseline")
    return _git(trial_dir, "rev-parse", "HEAD").stdout.strip()


def snapshot(trial_dir: Path) -> None:
    _git(trial_dir, "add", "-A")
    _git(trial_dir, "commit", "-qm", "agent", "--allow-empty")


def diff_numstat(trial_dir: Path, baseline: str) -> list[tuple[int, int, str]]:
    """(added, removed, path) per changed file, excluding infra paths."""
    out = _git(trial_dir, "diff", "--numstat", f"{baseline}..HEAD", "--",
               ".", *DIFF_EXCLUDES).stdout
    rows = []
    for line in out.splitlines():
        added, removed, path = line.split("\t", 2)
        rows.append((0 if added == "-" else int(added),
                     0 if removed == "-" else int(removed), path))
    return rows


def diff_patch(trial_dir: Path, baseline: str) -> str:
    return _git(trial_dir, "diff", f"{baseline}..HEAD", "--", ".", *DIFF_EXCLUDES).stdout


def restore_paths(trial_dir: Path, baseline: str, paths: list[str]) -> None:
    _git(trial_dir, "checkout", baseline, "--", *paths)


def apply_patch(trial_dir: Path, patch_file: Path) -> None:
    subprocess.run(["git", *GIT_ENV_ARGS, "apply", str(Path(patch_file).resolve())],
                   cwd=trial_dir, capture_output=True, text=True, check=True)
