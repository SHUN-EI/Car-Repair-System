"""pgvector / tsvector 辅助函数单测：分词、tsquery、距离换算、兼容点号。

不连数据库，也不依赖推理服务。
"""
from app.rag.lexical import (
    tokenize_repair_text,
    escape_tsquery_term,
    build_or_tsquery,
    cosine_distance_to_similarity,
    knowledge_point_id,
    manual_point_id,
    parse_point_id,
)


def test_tokenize_keeps_span_and_ngrams():
    tokens = tokenize_repair_text("注塑机温度过高")
    assert "注塑机温度过高" in tokens
    assert "注塑机" in tokens
    assert "温度" in tokens
    assert "过高" in tokens


def test_tokenize_keeps_english_and_numeric_tokens():
    tokens = tokenize_repair_text("PLC E001 过载")
    assert "PLC" in tokens
    assert "E001" in tokens
    assert "过载" in tokens


def test_tokenize_empty_and_short_ascii():
    assert tokenize_repair_text("") == []
    assert tokenize_repair_text("  ") == []
    assert "A" not in tokenize_repair_text("A 过载")


def test_escape_and_or_tsquery():
    assert escape_tsquery_term("过载&报警") == "过载报警"
    q = build_or_tsquery("注塑机过载")
    assert "注塑机" in q
    assert " | " in q
    assert "&" not in q


def test_cosine_distance_to_similarity_scale():
    assert cosine_distance_to_similarity(0) == 1.0
    assert cosine_distance_to_similarity(0.2) == 0.8
    assert cosine_distance_to_similarity(1) == 0.0
    assert cosine_distance_to_similarity(-0.1) == 1.0
    assert cosine_distance_to_similarity(1.5) == 0.0
    assert cosine_distance_to_similarity("bad") == 0.0


def test_point_id_roundtrip():
    assert knowledge_point_id(12) == "pg:k:12"
    assert manual_point_id(3) == "pg:m:3"
    assert parse_point_id("pg:k:12") == ("knowledge", 12)
    assert parse_point_id("pg:m:3") == ("manual", 3)
    assert parse_point_id("3f9a-old-uuid") is None
    assert parse_point_id("") is None
