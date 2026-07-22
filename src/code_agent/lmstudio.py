"""LMStudio server management: list, load, and query models."""

from __future__ import annotations

import requests


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
                loaded = bool(m.get("loaded_instances"))
                models.append({
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
        except Exception as e:
            return []

    def get_loaded_model(self) -> dict | None:
        models = self.list_models()
        for m in models:
            if m["loaded"]:
                return m
        return None

    def load_model(self, model_key: str, context_length: int | None = None, gpu_offload: float | None = None) -> dict:
        try:
            # LMStudio only wants "model"; extra fields can trigger 400s.
            payload: dict = {"model": model_key}
            resp = requests.post(
                f"{self._base}/api/v1/models/load",
                json=payload,
                timeout=300,  # big models take a while to load
            )
            resp.raise_for_status()
            return {"success": True, "model": model_key, "response": resp.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def unload_model(self, model_key: str) -> dict:
        try:
            resp = requests.post(
                f"{self._base}/api/v1/models/unload",
                json={"model": model_key},
                timeout=30,
            )
            resp.raise_for_status()
            return {"success": True, "model": model_key}
        except requests.exceptions.HTTPError:
            # Older LMStudio builds lack unload; loading a new model replaces the current one.
            return {"success": True, "model": model_key, "note": "Unload not supported; loading a new model will replace this one."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self._base}/api/v1/models", timeout=5)
            return resp.ok
        except Exception:
            return False
