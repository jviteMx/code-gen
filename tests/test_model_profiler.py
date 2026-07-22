"""Tests for the model profiler + router heuristics."""

from code_agent.coder.model_profiler import (
    profile, role_score, recommend, rank_for_role, _parse_params,
)


def _m(key, params="", ctype="llm", tool_use=False, vision=False, ctx=8192, loaded=True):
    return {"key": key, "display_name": key, "params": params, "quantization": "Q4",
            "max_context_length": ctx, "tool_use": tool_use, "vision": vision,
            "type": ctype, "loaded": loaded}


def test_parse_params():
    assert _parse_params("7B") == 7.0
    assert _parse_params("1.5B") == 1.5
    assert _parse_params("500M") == 0.5
    assert _parse_params("") == 0.0


def test_embedding_detected_by_type_and_name():
    p = profile(_m("nomic-embed-text-v1.5", ctype="embeddings"))
    assert p.is_embedding and "embedding" in p.kinds and not p.is_llm
    p2 = profile(_m("bge-large-en", ctype="llm"))  # name hint even if type mislabeled
    assert p2.is_embedding


def test_coder_detected():
    p = profile(_m("qwen2.5-coder-14b-instruct", params="14B", tool_use=True))
    assert "code" in p.kinds and p.tool_use and p.params_b == 14.0


def test_vision_detected():
    assert "vision" in profile(_m("llava-v1.6-mistral", params="7B")).kinds
    assert "vision" in profile(_m("qwen2-vl-7b", params="7B")).kinds
    assert "vision" in profile(_m("gemma-3-4b", params="4B", vision=True)).kinds


def test_reasoning_detected_by_name_or_size():
    assert "reasoning" in profile(_m("deepseek-r1-32b", params="32B")).kinds
    assert "reasoning" in profile(_m("llama-3.3-70b", params="70B")).kinds  # big → reasoning


def test_embedding_never_scores_for_chat_roles():
    p = profile(_m("nomic-embed-text", ctype="embeddings"))
    for role in ("main", "critic", "judge", "explore"):
        assert role_score(p, role) < 0


def test_coder_beats_general_for_main():
    coder = profile(_m("qwen2.5-coder-7b", params="7B", tool_use=True))
    general = profile(_m("mistral-7b-instruct", params="7B"))
    assert role_score(coder, "main") > role_score(general, "main")


def test_recommend_picks_coder_main_and_distinct_roles():
    models = [
        _m("nomic-embed-text-v1.5", ctype="embeddings"),          # excluded
        _m("qwen2.5-coder-14b", params="14B", tool_use=True),     # best coder
        _m("deepseek-r1-32b", params="32B"),                      # reasoner
        _m("gemma-2-27b", params="27B"),                          # big general
    ]
    profiles = [profile(m) for m in models]
    rec = recommend(profiles, roles=("main", "critic", "judge"))
    assert "coder" in rec["main"].key
    keys = {rec["main"].key, rec["critic"].key, rec["judge"].key}
    assert len(keys) == 3                       # all distinct
    assert all(not p.is_embedding for p in rec.values())  # never an embedding


def test_recommend_handles_single_model():
    profiles = [profile(_m("solo-7b", params="7B"))]
    rec = recommend(profiles)
    assert rec["main"].key == "solo-7b"


def test_recommend_empty_when_only_embeddings():
    profiles = [profile(_m("nomic-embed", ctype="embeddings"))]
    assert recommend(profiles) == {}
