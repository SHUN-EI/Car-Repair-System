"""多源去重键与检索入口签名，不依赖数据库。"""
from pathlib import Path

from app.agents.tools import rrf_merge
from app.rag.lexical import chunk_point_id, faq_point_id, obd_point_id, parse_point_id


def test_rrf_does_not_collide_across_source_types():
    """相同数值主键、不同来源前缀的条目不得被 RRF 合并。"""
    knowledge = [{"_dedup_key": "K:1", "id": 1, "knowledge_id": 1, "title": "案例", "score": 0.8, "method": "vector_search"}]
    obd = [{"_dedup_key": "O:1", "id": "obd-1", "obd_id": 1, "title": "P0300", "score": 1.0, "method": "obd_code_exact"}]
    chunk = [{"_dedup_key": "C:1", "id": "chunk-1", "chunk_id": 1, "title": "制动", "score": 0.7, "method": "manual_chunk_keyword"}]
    faq = [{"_dedup_key": "F:1", "id": "faq-1", "faq_id": 1, "title": "客服", "score": 0.6, "method": "faq_keyword_search"}]
    merged = rrf_merge([knowledge, obd, chunk, faq], top_n=10)
    keys = {item["_dedup_key"] for item in merged}
    assert keys == {"K:1", "O:1", "C:1", "F:1"}
    assert len(merged) == 4


def test_point_id_kinds_include_new_sources():
    """新来源使用 pg:o / pg:c / pg:f 点号，且可被解析。"""
    assert obd_point_id(4) == "pg:o:4"
    assert chunk_point_id(5) == "pg:c:5"
    assert faq_point_id(6) == "pg:f:6"
    assert parse_point_id("pg:o:4") == ("obd", 4)
    assert parse_point_id("pg:c:5") == ("chunk", 5)
    assert parse_point_id("pg:f:6") == ("faq", 6)
    assert parse_point_id("pg:k:12") == ("knowledge", 12)


def test_retrieve_hybrid_keeps_three_tuple_and_accepts_expand_flag():
    """retrieve_hybrid 仍返回三元组，并接受 expand_graph。"""
    text = (Path(__file__).resolve().parents[1] / "app" / "rag" / "retrieval_flow.py").read_text(encoding="utf-8")
    assert "def retrieve_hybrid(" in text
    assert "expand_graph: bool = True" in text
    assert "return merged, error_codes, tools" in text
