"""The tool loop must not accept an empty no-tool-call message as completion."""

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
        workdir=str(tmp_path), plan_mode=False, stream=False, **kw,
    )


def test_empty_response_gets_nudged(tmp_path):
    s = _session(tmp_path, FakeClient(turns=[Turn(content=""), Turn(content="all done")]))
    s._handle_direct("do the thing")
    nudges = [m for m in s.messages
              if m.get("role") == "user" and "message was empty" in str(m.get("content", ""))]
    assert len(nudges) == 1
    assert s.messages[-1].get("content") == "all done"


def test_empty_nudges_are_bounded(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="")))  # always empty
    s._handle_direct("do the thing")  # must terminate, not loop forever
    nudges = [m for m in s.messages
              if m.get("role") == "user" and "message was empty" in str(m.get("content", ""))]
    assert len(nudges) == 2


def test_normal_final_answer_not_nudged(tmp_path):
    s = _session(tmp_path, FakeClient(const=Turn(content="here is my summary")))
    s._handle_direct("do the thing")
    assert not any("message was empty" in str(m.get("content", "")) for m in s.messages)
