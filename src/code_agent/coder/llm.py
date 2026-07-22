"""One streaming interface over LMStudio (OpenAI-compatible) and Anthropic.

The rest of the app deals in Turn(content, tool_calls); each client writes
history back in its own vendor format.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Protocol


@dataclass
class Turn:
    content: str | None = None
    tool_calls: list[dict] = field(default_factory=list)


# Called with each streamed text fragment.
OnText = Callable[[str], None]


class LLMClient(Protocol):
    name: str
    model: str

    def stream(self, system_prompt: str, messages: list[dict], tools: list[dict],
               on_text: OnText | None = None) -> Turn: ...

    def complete(self, system_prompt: str, messages: list[dict], tools: list[dict]) -> Turn: ...

    def append_assistant(self, messages: list[dict], turn: Turn) -> None: ...

    def append_tool_results(self, messages: list[dict], results: list[tuple[str, str, str]]) -> None: ...
    """results are (tool_call_id, tool_name, content) tuples."""

    def for_model(self, model: str) -> "LLMClient": ...
    """Sibling client on another model, reusing the transport."""


# ── LMStudio / OpenAI-compatible ──────────────────────────────────────

class OpenAIClient:
    name = "lmstudio"

    def __init__(self, client, model: str, temperature: float = 0.2,
                 max_tokens: int | None = None, request_timeout: float | None = 600.0) -> None:
        self._client = client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.request_timeout = request_timeout

    def _kwargs(self, system_prompt, messages, tools, stream: bool) -> dict:
        kwargs: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "temperature": self.temperature,
            "stream": stream,
        }
        if tools:
            kwargs["tools"] = tools
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens
        if self.request_timeout:
            kwargs["timeout"] = self.request_timeout  # don't let a request hang forever
        return kwargs

    def complete(self, system_prompt, messages, tools) -> Turn:
        resp = self._client.chat.completions.create(**self._kwargs(system_prompt, messages, tools, False))
        if not getattr(resp, "choices", None):
            raise RuntimeError(_EMPTY_LMSTUDIO)
        msg = resp.choices[0].message
        return Turn(content=getattr(msg, "content", None),
                    tool_calls=_normalize_openai_tool_calls(getattr(msg, "tool_calls", None) or []))

    def stream(self, system_prompt, messages, tools, on_text=None) -> Turn:
        try:
            chunks = self._client.chat.completions.create(**self._kwargs(system_prompt, messages, tools, True))
        except TypeError:
            # Server rejected stream=True; fall back to a blocking call.
            turn = self.complete(system_prompt, messages, tools)
            if turn.content and on_text:
                on_text(turn.content)
            return turn

        text_parts: list[str] = []
        tool_frags: dict[int, dict] = {}
        saw_anything = False
        for chunk in chunks:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            saw_anything = True
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue
            piece = getattr(delta, "content", None)
            if piece:
                text_parts.append(piece)
                if on_text:
                    on_text(piece)
            for tc in getattr(delta, "tool_calls", None) or []:
                _accumulate_openai_tool_delta(tool_frags, tc)

        if not saw_anything:
            raise RuntimeError(_EMPTY_LMSTUDIO)

        tool_calls = [tool_frags[i] for i in sorted(tool_frags)]
        for tc in tool_calls:  # arguments must be a parseable json string
            if not tc["function"].get("arguments"):
                tc["function"]["arguments"] = "{}"
        return Turn(content="".join(text_parts) or None, tool_calls=tool_calls)

    def append_assistant(self, messages, turn) -> None:
        msg: dict = {"role": "assistant", "content": turn.content or ""}
        if turn.tool_calls:
            msg["tool_calls"] = turn.tool_calls
        messages.append(msg)

    def append_tool_results(self, messages, results) -> None:
        for tc_id, name, content in results:
            messages.append({"role": "tool", "tool_call_id": tc_id, "name": name, "content": content})

    def for_model(self, model: str) -> "OpenAIClient":
        return OpenAIClient(self._client, model, self.temperature, self.max_tokens, self.request_timeout)


# ── Anthropic ─────────────────────────────────────────────────────────

class AnthropicClient:
    name = "claude"

    def __init__(self, client, model: str, temperature: float = 0.2,
                 max_tokens: int = 8192, request_timeout: float | None = 600.0) -> None:
        self._client = client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.request_timeout = request_timeout

    def _kwargs(self, system_prompt, messages, tools) -> dict:
        kwargs: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system_prompt,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if self.request_timeout:
            kwargs["timeout"] = self.request_timeout
        return kwargs

    def complete(self, system_prompt, messages, tools) -> Turn:
        resp = self._client.messages.create(**self._kwargs(system_prompt, messages, tools))
        return _turn_from_anthropic(resp)

    def stream(self, system_prompt, messages, tools, on_text=None) -> Turn:
        with self._client.messages.stream(**self._kwargs(system_prompt, messages, tools)) as stream:
            if on_text:
                for piece in stream.text_stream:
                    on_text(piece)
            final = stream.get_final_message()
        return _turn_from_anthropic(final)

    def append_assistant(self, messages, turn) -> None:
        content: list[dict] = []
        if turn.content:
            content.append({"type": "text", "text": turn.content})
        for tc in turn.tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["function"]["name"],
                "input": json.loads(tc["function"]["arguments"] or "{}"),
            })
        messages.append({"role": "assistant", "content": content or [{"type": "text", "text": ""}]})

    def append_tool_results(self, messages, results) -> None:
        # Anthropic wants every tool_result for the turn in one user message.
        blocks = [{"type": "tool_result", "tool_use_id": tc_id, "content": content}
                  for tc_id, _name, content in results]
        if blocks:
            messages.append({"role": "user", "content": blocks})

    def for_model(self, model: str) -> "AnthropicClient":
        return AnthropicClient(self._client, model, self.temperature, self.max_tokens, self.request_timeout)


# ── cross-provider client registry ────────────────────────────────────

def is_claude_model(key: str) -> bool:
    return bool(key) and key.lower().startswith("claude")


CLAUDE_CONTEXT = 200_000


class ClientRegistry:
    """Maps a model key to the client for its backend.

    Lets a role (critic/judge/proposer) or the /model command point at either
    backend regardless of what the main session runs on. Either template may be
    None when that provider isn't configured.
    """

    def __init__(self, lmstudio: "OpenAIClient | None" = None,
                 anthropic: "AnthropicClient | None" = None,
                 claude_models: list[str] | None = None) -> None:
        self.lmstudio = lmstudio
        self.anthropic = anthropic
        # Keys we treat as Claude, so a local model named "claude-*" isn't misrouted.
        self._claude_keys = set(claude_models or [])
        if anthropic is not None:
            self._claude_keys.add(anthropic.model)

    def has_lmstudio(self) -> bool:
        return self.lmstudio is not None

    def has_claude(self) -> bool:
        return self.anthropic is not None

    def is_claude(self, model: str) -> bool:
        return model in self._claude_keys or (self.anthropic is not None and is_claude_model(model))

    def client_for(self, model: str) -> LLMClient:
        """Fresh client bound to `model`, on its owning backend."""
        if self.is_claude(model) and self.anthropic is not None:
            return self.anthropic.for_model(model)
        if self.lmstudio is not None:
            return self.lmstudio.for_model(model)
        if self.anthropic is not None:
            return self.anthropic.for_model(model)
        raise RuntimeError("No LLM backend is configured.")

    def claude_model_dicts(self) -> list[dict]:
        """Claude entries in the LMStudio dict shape, for /models and role assignment."""
        out = []
        for key in sorted(self._claude_keys):
            out.append({
                "key": key, "display_name": f"Claude · {key}",
                "architecture": "anthropic", "params": "cloud", "quantization": "",
                "size_gb": 0.0, "max_context_length": CLAUDE_CONTEXT,
                "tool_use": True, "vision": True, "loaded": True,
                "type": "llm", "provider": "claude",
            })
        return out


# ── helpers ───────────────────────────────────────────────────────────

_EMPTY_LMSTUDIO = (
    "LMStudio returned an empty response (no choices). The model may have "
    "crashed, run out of memory, or rejected the tool schema. Try /load to "
    "switch to a smaller model, or restart the LMStudio server."
)


def _normalize_openai_tool_calls(raw) -> list[dict]:
    out = []
    for tc in raw:
        fn = getattr(tc, "function", None)
        if fn is None:
            continue
        name = getattr(fn, "name", "") or ""
        args = getattr(fn, "arguments", "") or ""
        out.append({
            "id": getattr(tc, "id", None) or f"call_{name}",
            "type": "function",
            "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)},
        })
    return out


def _accumulate_openai_tool_delta(frags: dict[int, dict], tc) -> None:
    idx = getattr(tc, "index", 0) or 0
    slot = frags.setdefault(idx, {"id": None, "type": "function",
                                  "function": {"name": "", "arguments": ""}})
    if getattr(tc, "id", None):
        slot["id"] = tc.id
    fn = getattr(tc, "function", None)
    if fn is not None:
        if getattr(fn, "name", None):
            slot["function"]["name"] += fn.name
        if getattr(fn, "arguments", None):
            slot["function"]["arguments"] += fn.arguments
    if not slot["id"]:
        slot["id"] = f"call_{slot['function']['name'] or idx}"


def _turn_from_anthropic(resp) -> Turn:
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    for block in resp.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            args = block.input if isinstance(block.input, dict) else json.loads(block.input)
            tool_calls.append({
                "id": block.id,
                "type": "function",
                "function": {"name": block.name, "arguments": json.dumps(args)},
            })
    return Turn(content="\n".join(text_parts) if text_parts else None, tool_calls=tool_calls)
