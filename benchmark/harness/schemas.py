"""Dataclasses for task specs and results, plus their JSON forms."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

DEFAULT_WEIGHTS = {
    "f2p": 0.5,
    "p2p": 0.2,
    "localization": 0.1,
    "minimality": 0.1,
    "gate": 0.1,
}


@dataclass
class TaskSpec:
    id: str
    level: int
    title: str
    prompt: str
    dir: Path
    timeout_s: int = 900
    request_timeout_s: int = 240
    frontend: bool = False
    graders: list[str] = field(default_factory=lambda: ["pytest"])
    expected_files: list[str] = field(default_factory=list)
    p2p_ignore: list[str] = field(default_factory=list)
    schemathesis_paths: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)

    @property
    def effective_weights(self) -> dict[str, float]:
        return {**DEFAULT_WEIGHTS, **self.weights}

    @classmethod
    def load(cls, task_dir: Path) -> "TaskSpec":
        task_dir = Path(task_dir).resolve()  # graders run with cwd=trial
        meta = yaml.safe_load((task_dir / "task.yaml").read_text(encoding="utf-8"))
        prompt = (task_dir / "prompt.md").read_text(encoding="utf-8")
        return cls(
            id=meta["id"],
            level=int(meta["level"]),
            title=meta.get("title", meta["id"]),
            prompt=prompt,
            dir=task_dir,
            timeout_s=int(meta.get("timeout_s", 900)),
            request_timeout_s=int(meta.get("request_timeout_s", 240)),
            frontend=bool(meta.get("frontend", False)),
            graders=list(meta.get("graders", ["pytest"])),
            expected_files=list(meta.get("expected_files", [])),
            p2p_ignore=list(meta.get("p2p_ignore", [])),
            schemathesis_paths=list(meta.get("schemathesis_paths", [])),
            weights=dict(meta.get("weights", {})),
        )


@dataclass
class Subscores:
    f2p: float = 0.0
    p2p: float = 0.0
    localization: float = 0.0
    minimality: float = 0.0
    gate: float = 0.0


@dataclass
class TrialResult:
    task_id: str
    level: int
    trial: int
    resolved: bool = False
    subscores: Subscores = field(default_factory=Subscores)
    score: float = 0.0
    wall_s: float = 0.0
    requests: int | None = None
    tokens_used: int | None = None
    files_changed: int = 0
    loc_changed: int = 0
    timeout: bool = False
    exit_code: int | None = None
    p2p_tampered: bool = False
    failure: str | None = None
    error: str | None = None
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def weighted_score(sub: Subscores, weights: dict[str, float]) -> float:
    return round(sum(getattr(sub, k) * w for k, w in weights.items()), 4)
