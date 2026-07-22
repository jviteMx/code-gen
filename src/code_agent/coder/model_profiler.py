"""Classify LMStudio models (from metadata + name heuristics) and rank them per role.

The one firm rule: an embeddings-type model never gets a chat role. recommend()
is only a fallback for when no model is reachable to ask; /suggest normally asks
a loaded model instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_CODE_HINTS = ("coder", "code", "starcoder", "codestral", "codegemma", "codellama",
               "deepseek-coder", "codeqwen", "code-")
_EMBED_HINTS = ("embed", "nomic-embed", "bge-", "bge_", "e5-", "gte-", "sentence-")
_VISION_HINTS = ("-vl", "vl-", "vision", "llava", "multimodal", "-mm", "pixtral")
_REASON_HINTS = ("r1", "reason", "think", "qwq", "o1", "o3", "deepseek-r1", "phi-4")


@dataclass
class ModelProfile:
    key: str
    display_name: str
    params_b: float = 0.0       # billions of params (0 = unknown)
    context: int = 0
    tool_use: bool = False
    vision: bool = False
    is_embedding: bool = False
    loaded: bool = False
    kinds: set = field(default_factory=set)  # {"code","reasoning","vision","general","embedding"}

    @property
    def is_llm(self) -> bool:
        return not self.is_embedding

    def tags(self) -> str:
        parts = sorted(self.kinds)
        if self.tool_use:
            parts.append("tools")
        if self.params_b:
            parts.append(f"{self.params_b:g}B")
        return ", ".join(parts)


def _parse_params(s: str) -> float:
    """'7B' -> 7.0, '1.5B' -> 1.5, '500M' -> 0.5, '' -> 0.0."""
    if not s:
        return 0.0
    m = re.search(r"([\d.]+)\s*([bBmM])", s)
    if not m:
        return 0.0
    val = float(m.group(1))
    return val / 1000 if m.group(2).lower() == "m" else val


def profile(model: dict) -> ModelProfile:
    """Build a ModelProfile from an LMStudio model dict (see LMStudioManager)."""
    key = model.get("key", "")
    display = model.get("display_name", key)
    name = f"{key} {display}".lower()
    mtype = (model.get("type") or "llm").lower()

    is_embedding = mtype == "embeddings" or any(h in name for h in _EMBED_HINTS)
    vision = bool(model.get("vision")) or any(h in name for h in _VISION_HINTS)

    kinds: set = set()
    if is_embedding:
        kinds.add("embedding")
    else:
        if any(h in name for h in _CODE_HINTS):
            kinds.add("code")
        if vision:
            kinds.add("vision")
        params_b = _parse_params(model.get("params", ""))
        if any(h in name for h in _REASON_HINTS) or params_b >= 30:
            kinds.add("reasoning")
        if not kinds:
            kinds.add("general")

    return ModelProfile(
        key=key, display_name=display,
        params_b=_parse_params(model.get("params", "")),
        context=int(model.get("max_context_length") or 0),
        tool_use=bool(model.get("tool_use")),
        vision=vision, is_embedding=is_embedding,
        loaded=bool(model.get("loaded")), kinds=kinds,
    )


def role_score(p: ModelProfile, role: str) -> float:
    """Higher is better. Returns -1 for models that can't serve a chat role."""
    if p.is_embedding:
        return -1.0
    size = min(p.params_b, 70.0) / 70.0  # 0..1
    s = size * 1.5
    if role in ("main", "implement", "proposer"):
        s += 3.0 if "code" in p.kinds else 0.0
        s += 2.0 if p.tool_use else 0.0
        s += min(p.context, 200000) / 200000
    elif role in ("critic", "judge"):
        s += 2.0 if "reasoning" in p.kinds else 0.0
        s += 1.5 if p.params_b >= 14 else 0.0
        s += 1.0 if "code" in p.kinds else 0.0
    elif role == "explore":
        s += 1.5 if p.tool_use else 0.0
        s += (1.0 - size)          # smaller = faster to sweep
        s += 1.0 if "code" in p.kinds else 0.0
    elif role == "vision":
        s += 5.0 if "vision" in p.kinds else -1.0
    return s


def rank_for_role(profiles: list[ModelProfile], role: str) -> list[ModelProfile]:
    """Chat-capable models sorted best-first for a role."""
    eligible = [p for p in profiles if not p.is_embedding]
    return sorted(eligible, key=lambda p: role_score(p, role), reverse=True)


def recommend(profiles: list[ModelProfile],
              roles: tuple[str, ...] = ("main", "critic", "judge")) -> dict[str, ModelProfile]:
    """Greedily pick a distinct best model per role, reusing the top one if needed."""
    chat = [p for p in profiles if not p.is_embedding]
    if not chat:
        return {}
    chosen: dict[str, ModelProfile] = {}
    used: set = set()
    for role in roles:
        ranked = rank_for_role(chat, role)
        pick = next((p for p in ranked if p.key not in used), ranked[0] if ranked else None)
        if pick is None:
            continue
        chosen[role] = pick
        used.add(pick.key)
    return chosen
