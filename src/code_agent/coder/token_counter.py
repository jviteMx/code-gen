"""Token counting and context-window tracking.

Counts with a char/4 heuristic by default, or tiktoken (cl100k_base) if it's
installed. Local tokenizers vary, but that proxy beats char counting.
"""

from __future__ import annotations

import json

# Optional tiktoken encoder; None means fall back to the heuristic.
_ENCODER = None
_ENCODER_TRIED = False


def _get_encoder():
    global _ENCODER, _ENCODER_TRIED
    if _ENCODER_TRIED:
        return _ENCODER
    _ENCODER_TRIED = True
    try:
        import tiktoken

        _ENCODER = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _ENCODER = None
    return _ENCODER


def estimate_tokens(text: str) -> int:
    """Token estimate for a string (tiktoken if present, else ~4 chars/token)."""
    if not text:
        return 0
    enc = _get_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text, disallowed_special=()))
        except Exception:
            pass
    return max(1, len(text) // 4)


def _message_tokens(msg: dict) -> int:
    """Estimate tokens for a single message (content + any tool calls)."""
    total = 0
    content = msg.get("content", "")
    if isinstance(content, str):
        total += estimate_tokens(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                total += estimate_tokens(block.get("text", ""))
                inner = block.get("content", "")
                total += estimate_tokens(inner if isinstance(inner, str) else json.dumps(inner))
    for tc in msg.get("tool_calls", []) or []:
        if isinstance(tc, dict):
            fn = tc.get("function", {})
            total += estimate_tokens(fn.get("name", ""))
            total += estimate_tokens(fn.get("arguments", ""))
    return total + 4  # rough role/formatting overhead


def count_message_tokens(messages: list[dict]) -> int:
    """Estimate total tokens in a message list."""
    return sum(_message_tokens(m) for m in messages)


def trim_messages_to_fit(
    messages: list[dict],
    max_tokens: int,
    system_tokens: int,
    keep_recent: int = 10,
) -> list[dict]:
    """Trim old messages to fit the context window.

    Keeps the first user message and the last `keep_recent`, compresses big
    tool results in the middle before dropping whole messages, and leaves a
    marker where history was cut. The recent slice is grown leftward so it never
    starts on a dangling tool result.
    """
    budget = max_tokens - system_tokens
    current = count_message_tokens(messages)

    if current <= budget * 0.85:  # plenty of room, leave it alone
        return messages

    if len(messages) <= keep_recent + 1:
        return messages

    first = messages[:1]
    split = len(messages) - keep_recent
    # Don't start the tail on a tool response; it would be cut off from the
    # assistant tool_call that produced it. Walk left to a clean boundary.
    while split > 1 and _is_tool_response(messages[split]):
        split -= 1
    recent = messages[split:]
    middle = messages[1:split]

    trimmed_middle = list(middle)

    # First, shrink the big tool results in the middle.
    for i, msg in enumerate(trimmed_middle):
        if current <= budget * 0.75:
            break
        if _is_tool_response(msg):
            old_tokens = _message_tokens(msg)
            if old_tokens > 200:
                trimmed_middle[i] = _compress_tool_response(msg)
                current -= old_tokens - _message_tokens(trimmed_middle[i])

    # Still over? Drop whole middle messages.
    if current > budget * 0.75:
        while trimmed_middle and current > budget * 0.70:
            dropped = trimmed_middle.pop(0)
            current -= _message_tokens(dropped)
        # Don't leave a dangling tool response at the new head.
        while trimmed_middle and _is_tool_response(trimmed_middle[0]):
            current -= _message_tokens(trimmed_middle.pop(0))

    result = list(first)
    if len(trimmed_middle) < len(middle):
        dropped_count = len(middle) - len(trimmed_middle)
        result.append({
            "role": "user",
            "content": f"[Context trimmed: {dropped_count} earlier messages removed to fit the context window. Continue with the current task.]",
        })
    result.extend(trimmed_middle)
    result.extend(recent)
    return result


def _is_tool_response(msg: dict) -> bool:
    """True if the message carries a tool result (OpenAI 'tool' role, or an
    Anthropic user message whose content is a tool_result block list)."""
    if msg.get("role") == "tool":
        return True
    content = msg.get("content")
    if msg.get("role") == "user" and isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
    return False


def _compress_tool_response(msg: dict) -> dict:
    """Replace a large tool result's payload with a short placeholder."""
    if msg.get("role") == "tool":
        return {**msg, "content": "[Result truncated to save context]"}
    content = msg.get("content")
    if isinstance(content, list) and content:
        return {
            **msg,
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": content[0].get("tool_use_id", ""),
                    "content": "[Result truncated to save context]",
                }
            ],
        }
    return msg


def count_system_tokens(system_prompt: str, tools: list[dict]) -> int:
    """Estimate tokens used by system prompt + tool definitions."""
    return estimate_tokens(system_prompt) + estimate_tokens(json.dumps(tools))


class TokenTracker:
    """Tracks token usage across a session.

    `used_tokens` is the size of the next request: system prompt + tools + the
    whole conversation. Don't double-count the system prompt here, or small local
    context windows read as full way too early.
    """

    def __init__(self, context_window: int = 8192) -> None:
        self.context_window = context_window
        self.system_tokens = 0
        self.conversation_tokens = 0
        self.total_output_tokens = 0
        self.total_requests = 0

    def set_system_tokens(self, system_prompt: str, tools: list[dict]) -> None:
        self.system_tokens = count_system_tokens(system_prompt, tools)

    def record_request(self, messages: list[dict], response_text: str | None = None) -> None:
        self.total_requests += 1
        self.conversation_tokens = count_message_tokens(messages)
        if response_text:
            self.total_output_tokens += estimate_tokens(response_text)

    # Back-compat alias for callers that used total_input_tokens.
    @property
    def total_input_tokens(self) -> int:
        return self.used_tokens

    @property
    def used_tokens(self) -> int:
        return self.system_tokens + self.conversation_tokens

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.context_window - self.used_tokens)

    @property
    def usage_percent(self) -> float:
        if self.context_window == 0:
            return 0.0
        return min(100.0, (self.used_tokens / self.context_window) * 100)

    def format_status(self) -> str:
        """Format a compact status line with a usage bar."""
        pct = self.usage_percent
        color = "\033[92m" if pct < 50 else "\033[93m" if pct < 80 else "\033[91m"
        reset = "\033[0m"
        bar_width = 20
        filled = int(bar_width * pct / 100)
        bar = "█" * filled + "░" * (bar_width - filled)
        return (
            f"{color}[{bar}]{reset} "
            f"{_fmt_tokens(self.used_tokens)}/{_fmt_tokens(self.context_window)} tokens "
            f"({pct:.0f}%) | Requests: {self.total_requests}"
        )

    def format_compact(self) -> str:
        """Single-line compact format (no bar)."""
        pct = self.usage_percent
        color = "\033[92m" if pct < 50 else "\033[93m" if pct < 80 else "\033[91m"
        reset = "\033[0m"
        return f"{color}{_fmt_tokens(self.used_tokens)}/{_fmt_tokens(self.context_window)} ({pct:.0f}%){reset}"


def _fmt_tokens(n: int) -> str:
    """Format token count: 1234 -> '1.2k', 12345 -> '12k', 1_200_000 -> '1.2M'."""
    if n < 1000:
        return str(n)
    elif n < 10000:
        return f"{n/1000:.1f}k"
    elif n < 1000000:
        return f"{n/1000:.0f}k"
    else:
        return f"{n/1000000:.1f}M"


def get_model_context_size(
    provider: str,
    model: str = "default",
    lmstudio_url: str = "http://localhost:1234/v1",
) -> int:
    """Get the model's context window size from the API directly."""
    if provider == "claude":
        return 200000  # all current Claude models are >=200k

    import requests

    base = lmstudio_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]

    # Try the LMStudio native API first: /api/v1/models
    try:
        resp = requests.get(f"{base}/api/v1/models", timeout=10)
        if resp.ok:
            models_list = resp.json().get("models", [])
            for m in models_list:  # prefer the loaded model
                if m.get("loaded_instances"):
                    ctx = m.get("max_context_length")
                    if isinstance(ctx, int) and ctx > 0:
                        return ctx
            for m in models_list:  # else first model with a context length
                ctx = m.get("max_context_length")
                if isinstance(ctx, int) and ctx > 0:
                    return ctx
    except Exception:
        pass

    # Fall back to the OpenAI-compatible /v1/models.
    try:
        resp = requests.get(f"{base}/v1/models", timeout=10)
        if resp.ok:
            for m in resp.json().get("data", []):
                for field in ("max_context_length", "context_length", "context_window"):
                    val = m.get(field)
                    if isinstance(val, int) and val > 0:
                        return val
    except Exception:
        pass

    return 8192  # last-resort fallback


def get_loaded_model_info(
    lmstudio_url: str = "http://localhost:1234/v1", model_key: str | None = None,
) -> dict | None:
    """Get info about a selected loaded model, or the first loaded model."""
    import requests

    base = lmstudio_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]

    try:
        resp = requests.get(f"{base}/api/v1/models", timeout=10)
        if resp.ok:
            for m in resp.json().get("models", []):
                if m.get("loaded_instances") and (model_key is None or m.get("key") == model_key):
                    return {
                        "key": m.get("key", "unknown"),
                        "display_name": m.get("display_name", m.get("key", "unknown")),
                        "architecture": m.get("architecture", ""),
                        "params": m.get("params_string", ""),
                        "quantization": (m.get("quantization") or {}).get("name", ""),
                        "max_context_length": m.get("max_context_length", 0),
                        "tool_use": (m.get("capabilities") or {}).get("trained_for_tool_use", False),
                    }
    except Exception:
        pass
    return None
