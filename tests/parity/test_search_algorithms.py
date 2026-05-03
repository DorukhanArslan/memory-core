from memory_core.index.fts import bm25_rank_to_score, build_fts_query
from memory_core.index.hybrid import (
    HybridKeywordResult,
    HybridResult,
    HybridVectorResult,
    merge_hybrid_results,
)
from memory_core.index.mmr import mmr_rerank, tokenize
from memory_core.index.temporal_decay import calculate_temporal_decay_multiplier


def test_fts_query_quotes_tokens_with_and():
    assert build_fts_query('router vlan "prod"') == '"router" AND "vlan" AND "prod"'
    assert build_fts_query("!!!") is None


def test_bm25_rank_to_score_matches_upstream_formula():
    assert bm25_rank_to_score(-3.0) == 0.75
    assert bm25_rank_to_score(3.0) == 0.25


def test_hybrid_merge_combines_vector_and_keyword_scores():
    merged = merge_hybrid_results(
        vector=[HybridVectorResult("a", "MEMORY.md", 1, 2, "memory", "alpha", 0.8)],
        keyword=[HybridKeywordResult("a", "MEMORY.md", 1, 2, "memory", "alpha keyword", 0.4)],
        vector_weight=0.5,
        text_weight=0.5,
    )
    assert isinstance(merged[0], HybridResult)
    assert not hasattr(merged[0], "id")
    assert merged[0].score == 0.6000000000000001
    assert merged[0].snippet == "alpha keyword"


def test_mmr_tokenizer_handles_ascii_and_cjk():
    tokens = tokenize("Router VLAN 我喜欢你好")
    assert "router" in tokens
    assert "vlan" in tokens
    assert "我" in tokens
    assert "你好" in tokens


def test_temporal_decay_half_life():
    assert round(calculate_temporal_decay_multiplier(age_in_days=30, half_life_days=30), 3) == 0.5


def test_mmr_rerank_keeps_relevant_diverse_items():
    items = [
        {"id": "a", "score": 1.0, "content": "router vlan alpha"},
        {"id": "b", "score": 0.9, "content": "router vlan alpha duplicate"},
        {"id": "c", "score": 0.8, "content": "calendar preference"},
    ]
    ranked = mmr_rerank(items, enabled=True, lambda_=0.7)
    assert ranked[0]["id"] == "a"
    assert {item["id"] for item in ranked} == {"a", "b", "c"}
