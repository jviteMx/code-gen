"""Render results.json into a human-readable report.md."""

from __future__ import annotations

import json
from pathlib import Path

from . import metrics

LEVEL_NAMES = {
    1: "Function change",
    2: "Class change",
    3: "Module change",
    4: "Service change",
    5: "API contract change",
    6: "Frontend/CSS change",
    7: "Architecture change",
}


def render(results: dict) -> str:
    meta = results.get("meta", {})
    trials = results.get("trials", [])
    task_stats = metrics.per_task(trials)
    level_stats = metrics.per_level(task_stats)
    total = metrics.overall(task_stats)

    model = meta.get("model") or {}
    lines = ["# code-agent benchmark report", ""]
    lines.append(f"- **Run**: `{results.get('run_id', '?')}`"
                 + (" *(oracle mode — reference patches, no model)*" if meta.get("oracle") else ""))
    if model:
        ident = " | ".join(str(x) for x in [model.get("params"), model.get("quantization")] if x)
        lines.append(f"- **Model**: `{model.get('key', '?')}`" + (f" ({ident})" if ident else ""))
        context = meta.get("loaded_context_length") or model.get("loaded_context_length") \
            or model.get("max_context_length")
        if context:
            lines.append(f"- **Context**: {context:,} tokens"
                         f" | tool use: {model.get('tool_use', '?')}")
    if meta.get("agent_args"):
        lines.append(f"- **Agent configuration**: `{' '.join(meta['agent_args'])}` "
                     "(workflow-configured run; compare against bare runs as a separate configuration)")
    if meta.get("loaded_models") and len(meta["loaded_models"]) > 1:
        lines.append(f"- **⚠ Other models were loaded during this run**: "
                     f"{', '.join(meta['loaded_models'])} — VRAM contention may skew wall times")
    lines.append(f"- **Trials per task**: {meta.get('trials_per_task', 1)}")
    lines.append("")

    routing_events = [event for trial in trials
                      for event in (trial.get("routing", {}).get("events") or [])]
    if routing_events:
        initial = {}
        executed = {}
        for event in routing_events:
            if event.get("phase") == "initial":
                key = event.get("selected", "unknown")
                initial[key] = initial.get(key, 0) + 1
            if event.get("executed"):
                key = event.get("selected", "unknown")
                executed[key] = executed.get(key, 0) + 1
        lines.append("## Routing evidence")
        lines.append("")
        lines.append(f"- **Policy**: `{meta.get('routing_policy_version') or 'recorded by agent'}`")
        lines.append("- **Initial decisions**: " + ", ".join(
            f"{key} {count}" for key, count in sorted(initial.items())))
        lines.append("- **Executed orchestration routes**: " + (
            ", ".join(f"{key} {count}" for key, count in sorted(executed.items())) or "none"))
        lines.append(f"- **Configured worker cap**: {meta.get('effective_max_parallel', 1)}")
        lines.append("")

    lines.append(f"## Overall — score {total['mean_score']:.2f} ± {total['se']:.2f}, "
                 f"pass@1 {total['pass_at_1']:.2f} ({total['tasks']} tasks)")
    lines.append("")
    lines.append("## By level")
    lines.append("")
    lines.append("| Level | Name | Tasks | Score (mean ± SE) | pass@1 | Median wall (s) |")
    lines.append("|---|---|---|---|---|---|")
    for lvl, s in level_stats.items():
        lines.append(f"| L{lvl} | {LEVEL_NAMES.get(lvl, '?')} | {s['tasks']} "
                     f"| {s['mean_score']:.2f} ± {s['se']:.2f} | {s['pass_at_1']:.2f} "
                     f"| {s['median_wall_s']} |")
    lines.append("")

    lines.append("## By task")
    lines.append("")
    lines.append("| Task | n | Mean score | pass@1 | Median wall (s) | Median requests |")
    lines.append("|---|---|---|---|---|---|")
    for tid, s in task_stats.items():
        req = s["median_requests"] if s["median_requests"] is not None else "—"
        lines.append(f"| {tid} | {s['n']} | {s['mean_score']:.2f} | {s['pass_at_1']:.2f} "
                     f"| {s['median_wall_s']} | {req} |")
    lines.append("")

    failures = [t for t in trials if not t["resolved"]]
    if failures:
        lines.append("## Failure taxonomy")
        lines.append("")
        lines.append("| Task | Trial | Failure | Subscores (f2p/p2p/gate) | Notes |")
        lines.append("|---|---|---|---|---|")
        for t in failures:
            sub = t["subscores"]
            notes = []
            if t["timeout"]:
                notes.append("wall-timeout")
            if t["p2p_tampered"]:
                notes.append("edited P2P tests")
            if t.get("error"):
                notes.append(t["error"][:60])
            lines.append(f"| {t['task_id']} | {t['trial']} | {t.get('failure') or 'tests-failed'} "
                         f"| {sub['f2p']:.2f}/{sub['p2p']:.2f}/{sub['gate']:.2f} "
                         f"| {', '.join(notes) or '—'} |")
        lines.append("")

    lines.append("_Scoring per `benchmark/CRITERIA.md`: F2P 0.5 · P2P 0.2 · "
                 "localization 0.1 · minimality 0.1 · gate 0.1; task-clustered SE._")
    lines.append("")
    return "\n".join(lines)


def write_report(results_path: Path) -> Path:
    results = json.loads(results_path.read_text(encoding="utf-8"))
    out = results_path.parent / "report.md"
    out.write_text(render(results), encoding="utf-8")
    return out
