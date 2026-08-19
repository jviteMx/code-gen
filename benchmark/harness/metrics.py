"""Statistics: pass@k (Chen et al. 2021) and clustered mean ± SE (Miller 2024).

The task is the sampling unit: trial scores are averaged per task first, then
mean/SE are computed over task means, so trial count doesn't inflate confidence.
"""

from __future__ import annotations

import statistics
from math import comb, sqrt


def pass_at_k(n: int, c: int, k: int = 1) -> float:
    """Unbiased pass@k estimator over n trials with c successes."""
    if n <= 0 or k <= 0:
        return 0.0
    if k > n:
        k = n
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def mean_se(values: list[float]) -> tuple[float, float]:
    """(mean, standard error). SE is 0 for fewer than two values."""
    if not values:
        return (0.0, 0.0)
    m = statistics.fmean(values)
    if len(values) < 2:
        return (round(m, 4), 0.0)
    return (round(m, 4), round(statistics.stdev(values) / sqrt(len(values)), 4))


def per_task(trials: list[dict]) -> dict[str, dict]:
    """Group trial dicts by task: mean score, pass@1, trial count, medians."""
    tasks: dict[str, dict] = {}
    for t in trials:
        tasks.setdefault(t["task_id"], {"level": t["level"], "scores": [],
                                        "resolved": 0, "walls": [], "requests": []})
        entry = tasks[t["task_id"]]
        entry["scores"].append(t["score"])
        entry["resolved"] += 1 if t["resolved"] else 0
        entry["walls"].append(t["wall_s"])
        if t.get("requests") is not None:
            entry["requests"].append(t["requests"])
    out = {}
    for tid, e in sorted(tasks.items()):
        n = len(e["scores"])
        out[tid] = {
            "level": e["level"],
            "n": n,
            "mean_score": round(statistics.fmean(e["scores"]), 4),
            "pass_at_1": round(pass_at_k(n, e["resolved"], 1), 4),
            "median_wall_s": round(statistics.median(e["walls"]), 1),
            "median_requests": (statistics.median(e["requests"]) if e["requests"] else None),
            "scores": e["scores"],
        }
    return out


def per_level(task_stats: dict[str, dict]) -> dict[int, dict]:
    levels: dict[int, dict] = {}
    for tid, s in task_stats.items():
        levels.setdefault(s["level"], {"task_means": [], "pass1": [], "walls": []})
        levels[s["level"]]["task_means"].append(s["mean_score"])
        levels[s["level"]]["pass1"].append(s["pass_at_1"])
        levels[s["level"]]["walls"].append(s["median_wall_s"])
    out = {}
    for lvl, e in sorted(levels.items()):
        m, se = mean_se(e["task_means"])
        out[lvl] = {
            "tasks": len(e["task_means"]),
            "mean_score": m,
            "se": se,
            "pass_at_1": round(statistics.fmean(e["pass1"]), 4),
            "median_wall_s": round(statistics.median(e["walls"]), 1),
        }
    return out


def overall(task_stats: dict[str, dict]) -> dict:
    means = [s["mean_score"] for s in task_stats.values()]
    pass1 = [s["pass_at_1"] for s in task_stats.values()]
    m, se = mean_se(means)
    return {
        "tasks": len(means),
        "mean_score": m,
        "se": se,
        "pass_at_1": round(statistics.fmean(pass1), 4) if pass1 else 0.0,
    }
