"""Session-level orchestration wiring tests."""

import json

from code_agent.coder.llm import ClientRegistry, Turn
from code_agent.coder.session import CoderSession
from code_agent.coder.session_memory import SessionMemory
from code_agent.coder.token_counter import TokenTracker
from code_agent.coder.tool_executor import CodingToolExecutor
from code_agent.coder.ui import ReplUI

from test_orchestration import FakeClient


class FakeClaude(FakeClient):
    """Claude-flavoured fake (name='claude') for cross-provider routing tests."""
    name = "claude"

    def for_model(self, model):
        return FakeClaude(turns=self._turns, const=self._const, model=model)


def _session(tmp_path, client, **kw):
    return CoderSession(
        client=client, ui=ReplUI(str(tmp_path)),
        executor=CodingToolExecutor(str(tmp_path)),
        memory=SessionMemory(str(tmp_path)), tracker=TokenTracker(8192),
        workdir=str(tmp_path), plan_mode=True, **kw,
    )


def test_dispatch_tool_offered_in_exec_tools(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x")))
    names = {t.get("name") or t["function"]["name"] for t in s.tools_all}
    assert "dispatch_agents" in names
    # but not in the read-only plan tool set
    plan_names = {t.get("name") or t["function"]["name"] for t in s.tools_plan}
    assert "dispatch_agents" not in plan_names


def test_run_dispatch_agents_authorized(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="found the thing")), auto_approve=True)
    out = json.loads(s._run_dispatch_agents({"tasks": ["explore auth", "explore db"]}))
    assert len(out["agents"]) == 2
    assert "found the thing" in out["agents"][0]["findings"]


def test_run_dispatch_agents_declined(tmp_path, monkeypatch):
    s = _session(tmp_path, FakeClient(const=Turn(content="x")))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    out = json.loads(s._run_dispatch_agents({"tasks": ["a"]}))
    assert out["status"] == "declined by user"


def test_panel_sets_plan_and_approve_mode(tmp_path):
    judge_json = '{"scores":[{"index":0,"score":9}],"winner":0,"synthesis":"THE PLAN"}'
    s = _session(tmp_path, FakeClient(const=Turn(content=judge_json)))
    s._cmd_panel("design a rate limiter")
    assert s.current_plan == "THE PLAN"
    assert s.mode == "approve"


def test_proposer_specs_scale_with_models(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x")),
                 critic_model="model-B", judge_model="model-C", max_parallel_agents=5)
    specs = s._proposer_specs()
    models = {sp.client.model for sp in specs}
    assert {"fake", "model-B", "model-C"} <= models  # distinct models compete


def test_review_target_prefers_plan(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x")))
    s.current_plan = "my plan"
    target, kind = s._review_target("")
    assert kind == "plan" and target == "my plan"


def test_review_target_file(tmp_path):
    (tmp_path / "z.py").write_text("code here")
    s = _session(tmp_path, FakeClient(const=Turn(content="x")))
    target, kind = s._review_target("z.py")
    assert "code here" in target and kind.startswith("file")


# ── model discovery & role distribution ───────────────────────────────

def _fake_loaded(keys):
    return [{"key": k, "display_name": k, "params": "7B", "quantization": "Q4",
             "max_context_length": 8192, "loaded": True} for k in keys]


def test_roles_auto_distribute_across_loaded_models(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x"), model="A"))
    s._loaded_models = lambda: _fake_loaded(["A", "B", "C"])
    # critic/judge should auto-pick distinct models, not collapse to main
    assert s._eff_critic() == "B"
    assert s._eff_judge() == "C"


def test_panel_uses_distinct_models_when_multiple_loaded(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x"), model="A"))
    s._loaded_models = lambda: _fake_loaded(["A", "B", "C"])
    models = s._panel_models()
    assert models == ["A", "B", "C"]  # one proposer per loaded model
    specs = s._proposer_specs()
    assert {sp.client.model for sp in specs} == {"A", "B", "C"}


def test_panel_pads_single_model_with_copies(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x"), model="A"))
    s._loaded_models = lambda: _fake_loaded(["A"])
    models = s._panel_models()
    assert len(models) >= 2 and set(models) == {"A"}  # padded copies for diversity


def test_explicit_roles_win_over_autodistribute(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x"), model="A"),
                 critic_model="X", judge_model="Y")
    s._loaded_models = lambda: _fake_loaded(["A", "B", "C"])
    assert s._eff_critic() == "X" and s._eff_judge() == "Y"
    assert s._panel_models() == ["A", "X", "Y"]


def test_assign_sets_role(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x"), model="A"))
    s._loaded_models = lambda: _fake_loaded(["A", "B", "C"])
    s._cmd_assign("critic 2")
    assert s.critic_model == "B"
    s._cmd_assign("judge 3")
    assert s.judge_model == "C"


def test_embedding_models_excluded_from_roles(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x"), model="coder"))
    all_models = [
        {"key": "coder", "display_name": "coder", "params": "7B", "quantization": "Q4",
         "max_context_length": 8192, "loaded": True, "type": "llm", "tool_use": True, "vision": False},
        {"key": "nomic-embed", "display_name": "nomic-embed", "params": "", "quantization": "",
         "max_context_length": 2048, "loaded": True, "type": "embeddings", "tool_use": False, "vision": False},
    ]
    s._all_models = lambda: all_models
    assert s._chat_keys() == ["coder"]          # embedding filtered out
    assert s._eff_critic() == "coder"           # never the embedding model
    assert s._panel_models() and "nomic-embed" not in s._panel_models()


def test_llm_recommend_validates_and_corrects(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x"), model="coder"))
    models = [
        {"key": "coder", "display_name": "coder", "params": "7B", "max_context_length": 8192,
         "loaded": True, "type": "llm", "vision": False},
        {"key": "reasoner", "display_name": "reasoner", "params": "32B", "max_context_length": 16384,
         "loaded": True, "type": "llm", "vision": False},
        {"key": "embed", "display_name": "embed", "params": "", "max_context_length": 2048,
         "loaded": True, "type": "embeddings", "vision": False},
    ]
    # Router hallucinates a key for critic and (wrongly) picks the embedding for judge.
    s._router_client = lambda: FakeClient(const=Turn(
        content='{"main":"coder","critic":"ghost","judge":"embed","approach":"single","reason":"r"}'))
    rec = s._llm_recommend("summarize the code", models)
    assert rec["main"]["key"] == "coder"
    assert rec["critic"]["key"] in {"coder", "reasoner"}   # hallucinated 'ghost' corrected
    assert rec["judge"]["key"] != "embed"                  # embedding never chosen
    assert rec["approach"] == "single"


def test_classify_approach_reads_router_json(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x")))
    s._router_client = lambda: FakeClient(const=Turn(content='{"approach":"panel","reason":"hard design"}'))
    approach, reason = s._classify_approach("redesign the scheduler")
    assert approach == "panel" and "design" in reason


def test_auto_suggest_off_by_default(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x")))
    assert s.auto_orchestrate is False
    assert s._maybe_suggest("refactor the whole architecture") is False


def test_auto_suggest_single_task_not_escalated(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x")), auto_orchestrate=True)
    # Even a long summary/audit request stays single when the model says so.
    s._router_client = lambda: FakeClient(const=Turn(content='{"approach":"single","reason":"just summarize"}'))
    assert s._maybe_suggest("generate a summary document and tell me what is wrong " * 5) is False


# ── /model selection & Claude integration ─────────────────────────────

def test_model_selects_already_loaded_without_reload(tmp_path, monkeypatch):
    s = _session(tmp_path, FakeClient(const=Turn(content="x"), model="A"))
    s._all_models = lambda: _fake_loaded(["A", "B"])  # both already loaded

    class BoomMgr:  # any load attempt is a failure of the "no reload" contract
        def __init__(self, *a, **k):
            pass

        def load_model(self, *a, **k):
            raise AssertionError("must not reload an already-loaded model")

    monkeypatch.setattr("code_agent.lmstudio.LMStudioManager", BoomMgr)
    s._cmd_load("2")
    assert s.client.model == "B"
    assert s.tracker.context_window == 8192


def test_model_loads_when_not_loaded(tmp_path, monkeypatch):
    s = _session(tmp_path, FakeClient(const=Turn(content="x"), model="A"))
    models = _fake_loaded(["A"]) + [{"key": "C", "display_name": "C", "params": "7B",
                                     "quantization": "Q4", "max_context_length": 4096, "loaded": False}]
    s._all_models = lambda: models
    calls = {}

    class Mgr:
        def __init__(self, *a, **k):
            pass

        def load_model(self, key, context_length=None, **kw):
            calls["loaded"] = key
            calls["context"] = context_length
            return {"success": True, "context_length": context_length}

    monkeypatch.setattr("code_agent.lmstudio.LMStudioManager", Mgr)
    s._cmd_load("2")
    assert calls["loaded"] == "C"
    assert calls["context"] == 4096  # min(32768, model max of 4096)
    assert s.client.model == "C"


def _mixed_registry():
    lm = FakeClient(const=Turn(content="x"), model="local-1")
    claude = FakeClaude(const=Turn(content="x"), model="claude-sonnet-4")
    return lm, ClientRegistry(lmstudio=lm, anthropic=claude, claude_models=["claude-sonnet-4"])


def test_claude_listed_and_routed_to_anthropic(tmp_path):
    lm, reg = _mixed_registry()
    s = _session(tmp_path, lm, registry=reg)
    keys = {m["key"]: m for m in s._all_models()}
    assert keys["claude-sonnet-4"]["provider"] == "claude"       # Claude shows up
    # Assigning Claude to a role routes that role to the Anthropic client.
    s.judge_model = "claude-sonnet-4"
    assert s._client_for(s.judge_model).name == "claude"
    assert s._client_for("local-1").name == "lmstudio"           # local stays local


def test_select_main_to_claude_resets_history_and_tools(tmp_path):
    lm, reg = _mixed_registry()
    s = _session(tmp_path, lm, registry=reg)
    s.messages = [{"role": "user", "content": "earlier turn"}]
    s._select_main({"key": "claude-sonnet-4", "provider": "claude", "max_context_length": 200000})
    assert s.client.name == "claude"
    assert s.messages == []                                       # incompatible history dropped
    assert "name" in s.tools_all[0]                              # rebuilt in Anthropic schema shape
    assert s.tracker.context_window == 200000


def test_auto_roles_never_pick_cloud_on_local_main(tmp_path):
    lm, reg = _mixed_registry()
    s = _session(tmp_path, lm, registry=reg)
    # Main is local; only Claude + the single local model are available.
    s._all_models = lambda: (reg.claude_model_dicts() +
                             [{"key": "local-1", "display_name": "local-1", "params": "7B",
                               "max_context_length": 8192, "loaded": True, "provider": "lmstudio"}])
    assert "claude-sonnet-4" not in s._auto_chat_keys()          # cloud excluded from auto
    assert s._eff_critic() == "local-1"                          # falls back to main, not Claude
    assert s._eff_judge() == "local-1"


def test_preflight_reports_liveness(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="x"), model="A"))

    class Pinger:
        def __init__(self, key):
            self.model = key
            self.max_tokens = None
        def complete(self, *a):
            if self.model == "bad":
                raise RuntimeError("boom")
            return Turn(content="ok")

    s._own_client = lambda k: Pinger(k)
    results = {r[0]: r[1] for r in s._preflight(["good", "bad"])}
    assert results["good"] is True and results["bad"] is False
