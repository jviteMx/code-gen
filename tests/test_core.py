"""Tests for token accounting, message trimming, LLM shapes, and mentions."""

from pathlib import Path

from code_agent.coder.token_counter import (
    TokenTracker, count_message_tokens, trim_messages_to_fit,
)
from code_agent.coder.llm import (
    Turn, OpenAIClient, AnthropicClient, _accumulate_openai_tool_delta,
)
from code_agent.coder.ui import expand_file_mentions


# ── token accounting ──────────────────────────────────────────────────

def test_used_tokens_no_double_count():
    t = TokenTracker(context_window=10000)
    t.set_system_tokens("system prompt " * 50, [])
    msgs = [{"role": "user", "content": "hello world"}]
    t.record_request(msgs)
    assert t.used_tokens == t.system_tokens + t.conversation_tokens
    assert t.total_input_tokens == t.used_tokens


def test_remaining_and_percent():
    t = TokenTracker(context_window=1000)
    t.system_tokens = 200
    t.conversation_tokens = 300
    assert t.used_tokens == 500
    assert t.remaining_tokens == 500
    assert abs(t.usage_percent - 50.0) < 0.01


def test_trim_never_orphans_tool_result():
    # Build a long history ending in an assistant tool_call + tool result.
    msgs = [{"role": "user", "content": "start " * 50}]
    for i in range(20):
        msgs.append({"role": "assistant", "content": "x " * 50,
                     "tool_calls": [{"id": f"c{i}", "type": "function",
                                     "function": {"name": "read_file", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "name": "read_file",
                     "content": "result " * 100})
    trimmed = trim_messages_to_fit(msgs, max_tokens=2000, system_tokens=100, keep_recent=4)
    # tail shouldn't start with a tool response, or it'd be orphaned
    first_after_head = trimmed[1] if trimmed and trimmed[0].get("role") == "user" else trimmed[0]
    assert count_message_tokens(trimmed) < count_message_tokens(msgs)


# ── LLM vendor shapes ─────────────────────────────────────────────────

def test_openai_message_shapes():
    oc = OpenAIClient(client=None, model="m")
    turn = Turn(content="hi", tool_calls=[{"id": "c1", "type": "function",
                                           "function": {"name": "read_file", "arguments": "{}"}}])
    msgs = []
    oc.append_assistant(msgs, turn)
    oc.append_tool_results(msgs, [("c1", "read_file", "R")])
    assert msgs[0]["role"] == "assistant" and msgs[0]["tool_calls"]
    assert msgs[1]["role"] == "tool" and msgs[1]["tool_call_id"] == "c1"


def test_anthropic_batches_tool_results_in_one_message():
    ac = AnthropicClient(client=None, model="m")
    turn = Turn(tool_calls=[
        {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
        {"id": "c2", "type": "function", "function": {"name": "list_files", "arguments": "{}"}},
    ])
    msgs = []
    ac.append_assistant(msgs, turn)
    ac.append_tool_results(msgs, [("c1", "read_file", "R1"), ("c2", "list_files", "R2")])
    assert msgs[1]["role"] == "user"
    assert len(msgs[1]["content"]) == 2  # both results batched into one user message
    assert all(b["type"] == "tool_result" for b in msgs[1]["content"])


def test_openai_streamed_tool_call_assembly():
    class Frag:
        def __init__(self, index, id=None, name=None, args=None):
            self.index = index
            self.id = id
            self.function = type("F", (), {"name": name, "arguments": args})()

    frags = {}
    _accumulate_openai_tool_delta(frags, Frag(0, "c1", "read_", '{"pa'))
    _accumulate_openai_tool_delta(frags, Frag(0, None, "file", 'th":"x"}'))
    tc = frags[0]
    assert tc["function"]["name"] == "read_file"
    assert tc["function"]["arguments"] == '{"path":"x"}'


# ── @file mentions ────────────────────────────────────────────────────

def test_mention_injects_file(tmp_path):
    (tmp_path / "foo.py").write_text("print(1)\n")
    aug, attached = expand_file_mentions("check @foo.py please", str(tmp_path))
    assert attached == ["foo.py"] and "=== foo.py ===" in aug


def test_mention_escape_blocked(tmp_path):
    aug, attached = expand_file_mentions("read @../secret", str(tmp_path))
    assert attached == []


def test_mention_ignores_nonexistent(tmp_path):
    aug, attached = expand_file_mentions("email me @someone about it", str(tmp_path))
    assert attached == [] and aug == "email me @someone about it"


def test_loaded_model_info_follows_selected_model(monkeypatch):
    from code_agent.coder.token_counter import get_loaded_model_info

    class Response:
        ok = True

        def json(self):
            return {"models": [
                {"key": "large", "display_name": "Large", "loaded_instances": [{}],
                 "max_context_length": 100000},
                {"key": "small", "display_name": "Small", "loaded_instances": [{}],
                 "max_context_length": 32000},
            ]}

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: Response())
    assert get_loaded_model_info(model_key="small")["display_name"] == "Small"
    assert get_loaded_model_info(model_key="small")["max_context_length"] == 32000
