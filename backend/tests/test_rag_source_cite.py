"""来源标注、精确命中置顶：不依赖数据库和外部包。"""
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.rag.source_cite import (
    EXACT_METHODS,
    KEYWORD_SCORE_METHODS,
    format_source_line,
    infer_source_type,
    pin_exact_hits,
    source_priority,
)


def test_infer_and_labels():
    obd = {"obd_id": 1, "error_code": "P0300", "standard": "SAE J2012", "method": "obd_code_exact"}
    assert infer_source_type(obd) == "OBD"
    assert format_source_line(obd) == "OBD（SAE J2012·P0300）"

    chunk = {
        "chunk_id": 9,
        "source_type": "OEM_MANUAL",
        "manual_name": "制动系统",
        "chapter": "第5章",
        "page": "5-12",
    }
    assert format_source_line(chunk) == "原厂手册（制动系统·第5章·5-12）"

    faq = {"faq_id": 3, "title": "刹车有点紧常见原因"}
    assert infer_source_type(faq) == "FAQ"
    assert format_source_line(faq) == "客服知识"

    case = {"knowledge_id": 12, "title": "怠速抖动"}
    assert infer_source_type(case) == "CASE"
    assert format_source_line(case) == "工单案例"

    manual = {
        "manual_code_id": 8,
        "manual_name": "伺服手册",
        "chapter": "第3章",
        "page": "3-10",
        "error_code": "SV0401",
    }
    assert infer_source_type(manual) == "MANUAL"
    assert format_source_line(manual) == "手册（伺服手册·第3章·3-10·错误码 SV0401）"


def test_conflict_priority():
    assert source_priority({"source_type": "OBD"}) < source_priority({"source_type": "CASE"})
    assert source_priority({"source_type": "OEM_MANUAL"}) < source_priority({"source_type": "FAQ"})
    assert source_priority({"source_type": "CASE"}) < source_priority({"source_type": "FAQ"})


def test_pin_exact_hits_keeps_exact_and_caps_rest():
    items = (
        [{"method": "vector_search", "id": i} for i in range(5)]
        + [{"method": "obd_code_exact", "id": "P0300"}]
        + [{"method": "manual_code_exact", "id": "SV0401"}]
    )
    pinned = pin_exact_hits(items, top_k=3)
    assert [x["method"] for x in pinned] == ["obd_code_exact", "manual_code_exact", "vector_search"]
    assert pinned[2]["id"] == 0


def test_pin_exact_never_drops_exact_even_if_over_top_k():
    exact = [{"method": "obd_code_exact", "id": i} for i in range(4)]
    pinned = pin_exact_hits(exact + [{"method": "bm25_search", "id": "x"}], top_k=2)
    assert len(pinned) == 4
    assert all(item["method"] in EXACT_METHODS for item in pinned)


def test_keyword_methods_cover_new_paths():
    assert "bm25_search" in KEYWORD_SCORE_METHODS
    assert "obd_keyword_search" in KEYWORD_SCORE_METHODS
    assert "manual_chunk_keyword" in KEYWORD_SCORE_METHODS
    assert "faq_keyword_search" in KEYWORD_SCORE_METHODS
    assert "obd_code_exact" not in KEYWORD_SCORE_METHODS
    assert "obd_vector_search" not in KEYWORD_SCORE_METHODS
