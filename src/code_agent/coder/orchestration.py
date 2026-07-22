"""Sub-agent orchestration: fan-out plus critic/judge/MoE patterns.

Fan-out agents are read-only, so the main session stays the only writer. Work is
threaded (the calls are network-bound); keep max_workers <= your LMStudio limit.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

from code_agent.coder.coding_tools import CODING_TOOLS, PLAN_TOOL_NAMES, to_openai_format
from code_agent.coder.llm import LLMClient
from code_agent.coder.tool_executor import CodingToolExecutor

READ_ONLY_TOOLS = [t for t in CODING_TOOLS if t["name"] in PLAN_TOOL_NAMES]


@dataclass
class AgentSpec:
    name: str
    client: LLMClient
    system_prompt: str
    tools: list[dict] = field(default_factory=list)  # vendor-format for client
    max_rounds: int = 10
    workdir: str = "."
    read_only: bool = True


@dataclass
class AgentResult:
    name: str
    text: str = ""
    structured: dict | None = None
    rounds: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def read_only_tools_for(client: LLMClient) -> list[dict]:
    if client.name == "claude":
        return [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                for t in READ_ONLY_TOOLS]
    return to_openai_format(READ_ONLY_TOOLS)


# ── core: run one sub-agent (headless, non-streaming, bounded) ─────────

def run_agent(spec: AgentSpec, task: str,
              on_event: Callable[[str, str], None] | None = None) -> AgentResult:
    """Bounded headless tool loop for one sub-agent; returns its final text."""
    executor = CodingToolExecutor(spec.workdir)  # per-agent, no shared state
    allowed = {t.get("name") or t.get("function", {}).get("name") for t in spec.tools}
    messages: list[dict] = [{"role": "user", "content": task}]
    last_text = ""
    last_sig = None
    repeat = 0

    for rnd in range(1, spec.max_rounds + 1):
        try:
            turn = spec.client.complete(spec.system_prompt, messages, spec.tools)
        except Exception as e:
            return AgentResult(spec.name, text=last_text, rounds=rnd, error=str(e))

        if turn.content:
            last_text = turn.content

        if not turn.tool_calls:
            break

        sig = (turn.tool_calls[0]["function"]["name"], turn.tool_calls[0]["function"]["arguments"])
        repeat = repeat + 1 if sig == last_sig else 0
        last_sig = sig
        if repeat >= 2:
            break

        spec.client.append_assistant(messages, turn)
        results: list[tuple[str, str, str]] = []
        for tc in turn.tool_calls:
            name = tc["function"]["name"]
            tc_id = tc.get("id") or f"call_{name}"
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except Exception:
                args = {}
            if spec.read_only and name not in allowed:
                results.append((tc_id, name, json.dumps({"error": f"{name} is not permitted for a read-only agent"})))
                continue
            if on_event:
                on_event(spec.name, f"{name} {json.dumps(args)[:80]}")
            results.append((tc_id, name, executor.execute(name, args)))
        spec.client.append_tool_results(messages, results)

    return AgentResult(spec.name, text=last_text, rounds=rnd,
                       structured=extract_json(last_text))


# ── parallel primitive ────────────────────────────────────────────────

def parallel(thunks: list[Callable[[], object]], max_workers: int = 5) -> list:
    """Run thunks concurrently, results in the original order.

    A thunk that raises comes back as the exception object rather than
    propagating, so callers can filter. On Ctrl+C we cancel queued work and
    re-raise without waiting on in-flight requests (they have their own timeout).
    We avoid `with ThreadPoolExecutor(...)`: its __exit__ blocks on live workers
    and would swallow the interrupt.
    """
    if not thunks:
        return []
    results: list = [None] * len(thunks)
    pool = ThreadPoolExecutor(max_workers=max(1, max_workers))
    futs = {pool.submit(t): i for i, t in enumerate(thunks)}
    try:
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                results[i] = fut.result()
            except Exception as e:  # noqa: BLE001  (return it, don't raise)
                results[i] = e
    except KeyboardInterrupt:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=False)
    return results


# ── patterns ──────────────────────────────────────────────────────────

def critic_review(target: str, kind: str, critic: AgentSpec) -> AgentResult:
    """One critic reviews a plan/diff. Structured verdict in .structured."""
    task = (f"Review the following {kind}. Verify against the actual code using your "
            f"read-only tools before judging.\n\n=== {kind.upper()} ===\n{target}\n")
    res = run_agent(critic, task)
    if res.structured is None:
        res.structured = {"verdict": "revise", "issues": [], "summary": res.text[:200]}
    return res


def judge_panel(task: str, proposers: list[AgentSpec], judge: AgentSpec,
                max_workers: int = 5) -> dict:
    """Proposers draft in parallel; a judge scores and synthesizes a winner.

    Returns {proposals, verdict, winner_index, winner_text, synthesis}.
    """
    proposals = parallel([_bind(run_agent, s, task) for s in proposers], max_workers)
    proposals = [p if isinstance(p, AgentResult) else AgentResult(f"proposer{i}", error=str(p))
                 for i, p in enumerate(proposals)]

    valid = [(i, p) for i, p in enumerate(proposals) if p.ok and p.text.strip()]
    if not valid:
        return {"proposals": proposals, "verdict": None, "winner_index": -1,
                "winner_text": "", "synthesis": ""}
    if len(valid) == 1:
        i, p = valid[0]
        return {"proposals": proposals, "verdict": None, "winner_index": i,
                "winner_text": p.text, "synthesis": p.text}

    catalog = "\n\n".join(f"### Proposal {i}\n{p.text}" for i, p in valid)
    judge_task = f"TASK:\n{task}\n\nCANDIDATE PROPOSALS:\n{catalog}"
    verdict_res = run_agent(judge, judge_task)
    verdict = verdict_res.structured or {}
    winner = verdict.get("winner")
    if not isinstance(winner, int) or winner not in [i for i, _ in valid]:
        winner = valid[0][0]
    winner_text = next(p.text for i, p in valid if i == winner)
    synthesis = verdict.get("synthesis") or winner_text
    return {"proposals": proposals, "verdict": verdict, "winner_index": winner,
            "winner_text": winner_text, "synthesis": synthesis}


def parallel_investigate(subtasks: list[str], make_spec: Callable[[str], AgentSpec],
                         max_workers: int = 5) -> list[AgentResult]:
    """Run one read-only explorer per subtask, concurrently."""
    thunks = [_bind_task(make_spec, st) for st in subtasks]
    out = parallel(thunks, max_workers)
    return [r if isinstance(r, AgentResult) else AgentResult("explorer", error=str(r)) for r in out]


# ── helpers ───────────────────────────────────────────────────────────

def _bind(fn, spec, task):
    return lambda: fn(spec, task)


def _bind_task(make_spec, subtask):
    def thunk():
        return run_agent(make_spec(subtask), subtask)
    return thunk


def extract_json(text: str | None) -> dict | None:
    """Pull a JSON object out of a model reply, prose around it and all."""
    if not text:
        return None
    text = text.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        break
        start = text.find("{", start + 1)
    return None
