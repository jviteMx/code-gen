"""Tests for /model unload prompts and the load/unload toggle."""

import code_agent.lmstudio as lmstudio_mod
from code_agent.coder.llm import Turn
from code_agent.coder.session import CoderSession
from code_agent.coder.session_memory import SessionMemory
from code_agent.coder.token_counter import TokenTracker
from code_agent.coder.tool_executor import CodingToolExecutor
from code_agent.coder.ui import ReplUI

from test_orchestration import FakeClient


def _session(tmp_path, client, **kw):
    return CoderSession(
        client=client, ui=ReplUI(str(tmp_path)),
        executor=CodingToolExecutor(str(tmp_path)),
        memory=SessionMemory(str(tmp_path)), tracker=TokenTracker(8192),
        workdir=str(tmp_path), plan_mode=False, **kw,
    )


class FakeMgr:
    unloaded: list = []
    loaded: list = []

    def __init__(self, url):
        pass

    def load_model(self, key, **kw):
        FakeMgr.loaded.append(key)
        return {"success": True}

    def unload_model(self, key):
        FakeMgr.unloaded.append(key)
        return {"success": True}


def _m(key, loaded=True):
    return {"key": key, "display_name": key, "loaded": loaded,
            "provider": "lmstudio", "type": "llm", "max_context_length": 8192}


def _setup(tmp_path, monkeypatch, models, answers):
    FakeMgr.unloaded, FakeMgr.loaded = [], []
    monkeypatch.setattr(lmstudio_mod, "LMStudioManager", FakeMgr)
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(it))
    s = _session(tmp_path, FakeClient(const=Turn(content="x"), model="m1"))
    monkeypatch.setattr(s, "_all_models", lambda: models)
    return s


def test_toggle_unloads_current_main_and_falls_back(tmp_path, monkeypatch):
    s = _setup(tmp_path, monkeypatch, [_m("m1"), _m("m2")], answers=[""])  # Enter = yes
    s._cmd_load("1")
    assert FakeMgr.unloaded == ["m1"]
    assert s.client.model == "m2"  # fell back to the other loaded chat model


def test_toggle_declined_keeps_model(tmp_path, monkeypatch):
    s = _setup(tmp_path, monkeypatch, [_m("m1"), _m("m2")], answers=["n"])
    s._cmd_load("1")
    assert FakeMgr.unloaded == []
    assert s.client.model == "m1"


def test_fresh_load_offers_unload_of_previous(tmp_path, monkeypatch):
    s = _setup(tmp_path, monkeypatch, [_m("m1"), _m("m2", loaded=False)], answers=[""])
    s._cmd_load("2")
    assert FakeMgr.loaded == ["m2"]
    assert s.client.model == "m2"
    assert FakeMgr.unloaded == ["m1"]  # default answer is yes on a fresh load


def test_fresh_load_unload_declined(tmp_path, monkeypatch):
    s = _setup(tmp_path, monkeypatch, [_m("m1"), _m("m2", loaded=False)], answers=["n"])
    s._cmd_load("2")
    assert s.client.model == "m2"
    assert FakeMgr.unloaded == []


def test_switch_between_loaded_defaults_to_keep(tmp_path, monkeypatch):
    s = _setup(tmp_path, monkeypatch, [_m("m1"), _m("m2")], answers=[""])  # Enter = no here
    s._cmd_load("2")
    assert s.client.model == "m2"
    assert FakeMgr.unloaded == []  # both stay resident for orchestration by default