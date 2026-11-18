"""问句解析：症状别名与 OBD 码抽取，不依赖数据库。"""
from app.rag.query_parse import (
    SYMPTOM_ALIASES,
    extract_obd_codes,
    extract_symptoms,
    parse_consult_query,
)


def test_brake_tight_maps_to_canonical_symptom():
    """「刹车有点紧」应归到规范名「刹车紧」。"""
    parsed = parse_consult_query("刹车有点紧，是什么原因", existing_error_codes=[])
    assert parsed.symptoms == ["刹车紧"]
    assert parsed.error_codes == []
    assert parsed.canonical_keys == ["刹车紧"]


def test_idle_shake_with_p0300():
    """「热车怠速抖动，读到 P0300」应同时抽出症状和标准码。"""
    parsed = parse_consult_query("热车怠速抖动，读到 P0300", existing_error_codes=[])
    assert "怠速抖动" in parsed.symptoms
    assert "P0300" in parsed.error_codes


def test_extract_obd_codes_normalizes_case():
    """小写 p0300 应规范成 P0300，且去重。"""
    assert extract_obd_codes("读到 p0300 和 P0300") == ["P0300"]
    assert extract_obd_codes("C0035 左前轮速") == ["C0035"]


def test_longer_alias_wins():
    """更长的别名优先，避免短词重复命中。"""
    assert extract_symptoms("刹车有点紧") == ["刹车紧"]
    assert "刹车有点紧" in SYMPTOM_ALIASES


def test_extra_aliases_from_graph():
    """图谱读出的别名可以补充内置表。"""
    parsed = parse_consult_query(
        "车子发拖是怎么回事",
        extra_aliases=[("车子发拖", "刹车紧")],
    )
    assert parsed.symptoms == ["刹车紧"]
