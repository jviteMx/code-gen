"""LMStudio server management: list, load, and query models."""

from __future__ import annotations

import requests

# LMStudio's JIT/API default context is 4096 — far too small for an agentic
# tool loop (system prompt + tools alone approach that). Loads request this
# much unless told otherwise, capped by the model's own maximum.
DEFAULT_LOAD_CONTEXT = 32768


def _instance_context(inst) -> int | None:
    """Best-effort effective context length of a loaded instance dict."""
    if not isinstance(inst, dict):
        return None
    for key in ("context_length", "contextLength", "n_ctx"):
        if isinstance(inst.get(key), int):
            return inst[key]
    config = inst.get("config")
    if isinstance(config, dict):
        for key in ("context_length", "contextLength", "n_ctx"):
            if isinstance(config.get(key), int):
                return config[key]
    return None


class LMStudioManager:
    """Wrapper over LMStudio's /api/v1/ management endpoints."""

    def __init__(self, base_url: str = "http://localhost:1234") -> None:
        self._base = base_url.rstrip("/")
        if self._base.endswith("/v1"):
            self._base = self._base[:-3]

    def list_models(self) -> list[dict]:
        try:
            resp = requests.get(f"{self._base}/api/v1/models", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            models = []
            for m in data.get("models", []):
                instances = m.get("loaded_instances") or []
                loaded = bool(instances)
                loaded_ctx = next((c for c in map(_instance_context, instances) if c), None)
                models.append({
                    "loaded_context_length": loaded_ctx,
                    "key": m.get("key", ""),
                    "display_name": m.get("display_name", m.get("key", "")),
                    "architecture": m.get("architecture", ""),
                    "params": m.get("params_string", ""),
                    "quantization": (m.get("quantization") or {}).get("name", ""),
                    "size_gb": round(m.get("size_bytes", 0) / (1024**3), 1),
                    "max_context_length": m.get("max_context_length", 0),
                    "tool_use": (m.get("capabilities") or {}).get("trained_for_tool_use", False),
                    "vision": (m.get("capabilities") or {}).get("vision", False),
                    "loaded": loaded,
                    "type": m.get("type", "llm"),
                })
            return models
        except Exception:
            return []

    def get_loaded_model(self) -> dict | None:
        models = self.list_models()
        for m in models:
            if m["loaded"]:
                return m
        return None

    def load_model(self, model_key: str, context_length: int | None = None,
                   gpu_offload: float | None = None) -> dict:
        """Load a model, requesting a context length when given.

        Different LMStudio builds accept the context under different fields (or
        not at all), so shapes are tried in order; a 4xx never loads anything,
        so falling through is safe. The effective context is reported back so
        callers can see whether the request was honored.
        """
        payloads: list[dict] = [{"model": model_key}]
        if context_length:
            payloads = [
                {"model": model_key, "context_length": context_length},
                {"model": model_key, "config": {"context_length": context_length}},
                {"model": model_key},
            ]
        last_error = "no load attempt made"
        for payload in payloads:
            try:
                resp = requests.post(
                    f"{self._base}/api/v1/models/load",
                    json=payload,
                    timeout=300,  # big models take a while to load
                )
                resp.raise_for_status()
            except Exception as e:
                last_error = str(e)
                continue
            loaded = next((m for m in self.list_models() if m["key"] == model_key), None)
            return {"success": True, "model": model_key,
                    "context_length": (loaded or {}).get("loaded_context_length"),
                    "requested_context": context_length}
        return {"success": False, "error": last_error}

    def _instance_ids(self, model_key: str) -> list[str]:
        """instance_ids of the loaded instances of a model (raw API shape)."""
        try:
            resp = requests.get(f"{self._base}/api/v1/models", timeout=10)
            resp.raise_for_status()
            for m in resp.json().get("models", []):
                if m.get("key") != model_key:
                    continue
                ids = []
                for inst in m.get("loaded_instances") or []:
                    if isinstance(inst, dict):
                        iid = inst.get("instance_id") or inst.get("id") or inst.get("identifier")
                        if iid:
                            ids.append(iid)
                    elif isinstance(inst, str):
                        ids.append(inst)
                return ids
        except Exception:
            pass
        return []

    def unload_model(self, model_key: str) -> dict:
        """Unload a model. Newer LMStudio builds require the instance_id;
        older ones accept the model key — try both, and verify the result."""
        attempts: list[dict] = [{"instance_id": iid} for iid in self._instance_ids(model_key)]
        attempts.append({"model": model_key})
        errors = []
        for payload in attempts:
            try:
                resp = requests.post(f"{self._base}/api/v1/models/unload",
                                     json=payload, timeout=30)
                resp.raise_for_status()
            except Exception as e:
                errors.append(str(e))
                continue
            # trust but verify: some builds return 200 without unloading
            if not any(m["key"] == model_key and m["loaded"] for m in self.list_models()):
                return {"success": True, "model": model_key}
        return {"success": False, "model": model_key,
                "error": errors[-1] if errors else "server reports the model is still loaded"}

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self._base}/api/v1/models", timeout=5)
            return resp.ok
        except Exception:
            return False
