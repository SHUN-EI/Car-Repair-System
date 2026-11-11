"""检索质量阀门优先看 rerank_score。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.retrieval_flow import case_rank_score, evaluate_retrieval_quality


def test_rank_score_prefers_rerank_over_zero_vector_score():
    item = {"score": 0, "rerank_score": 0.82, "rrf_score": 0.01}
    assert case_rank_score(item) == 0.82


def test_quality_gate_does_not_treat_reranked_hits_as_empty():
    results = [
        {"score": 0, "rerank_score": 0.91},
        {"score": 0, "rerank_score": 0.84},
        {"score": 0, "rerank_score": 0.77},
    ]
    verdict = evaluate_retrieval_quality(results)
    assert verdict["sufficient"] is True
    assert verdict["max_score"] >= 0.9


def test_quality_gate_uses_low_rerank_even_if_vector_score_is_high():
    results = [
        {"score": 0.95, "rerank_score": 0.1},
        {"score": 0.93, "rerank_score": 0.2},
        {"score": 0.9, "rerank_score": 0.15},
    ]
    verdict = evaluate_retrieval_quality(results)
    assert verdict["sufficient"] is False
