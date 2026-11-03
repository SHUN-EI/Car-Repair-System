"""保养套餐 / 服务项目推荐。按车型、里程、症状做规则排序，不调用模型，也不编造命中率。"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def _norm(value: Any) -> str:
    return ("" if value is None else str(value)).strip().casefold()


def _keywords(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        value = [part for part in value.replace("，", ",").split(",")]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _field_matches(rule_value: Any, query_value: Any) -> bool:
    expected = _norm(rule_value)
    if not expected:
        return True
    return expected == _norm(query_value)


def _mileage_matches(mileage: Optional[int], start: Any, end: Any) -> bool:
    if mileage is None:
        return True
    if start is None and end is None:
        return True
    left = 0 if start is None else int(start)
    right = 10 ** 9 if end is None else int(end)
    return left <= int(mileage) <= right


def _symptom_hits(keywords: Iterable[str], symptoms: str) -> int:
    blob = _norm(symptoms)
    if not blob:
        return 0
    hits = 0
    for word in keywords:
        if _norm(word) and _norm(word) in blob:
            hits += 1
    return hits


def rank_offers(
    rows: List[dict],
    *,
    brand: Any = None,
    series: Any = None,
    mileage: Optional[int] = None,
    symptoms: Any = None,
) -> List[dict]:
    """硬条件：品牌、车系、里程区间。症状只参与排序和原因说明。"""
    symptom_text = "" if symptoms is None else str(symptoms)
    ranked: List[dict] = []
    for row in rows:
        if row.get("is_active") is False:
            continue
        if not _field_matches(row.get("brand"), brand):
            continue
        if not _field_matches(row.get("series"), series):
            continue
        if not _mileage_matches(mileage, row.get("mileage_from"), row.get("mileage_to")):
            continue
        words = _keywords(row.get("symptom_keywords"))
        hits = _symptom_hits(words, symptom_text)
        score = hits
        reasons: List[str] = []
        if _norm(row.get("brand")) and _norm(row.get("brand")) == _norm(brand):
            score += 3
            reasons.append(f"品牌{row.get('brand')}")
        elif not _norm(row.get("brand")):
            reasons.append("品牌不限")
        if _norm(row.get("series")) and _norm(row.get("series")) == _norm(series):
            score += 2
            reasons.append(f"车系{row.get('series')}")
        if mileage is not None and (row.get("mileage_from") is not None or row.get("mileage_to") is not None):
            score += 3
            reasons.append(f"里程{mileage}km")
        if hits:
            reasons.append(f"症状命中{hits}个关键词")
        elif symptom_text.strip() and words:
            reasons.append("症状未命中关键词，仍保留在里程和车型范围内")
        ranked.append({
            **row,
            "score": score,
            "symptom_hits": hits,
            "reason": "，".join(reasons) or "常规项目",
        })
    ranked.sort(key=lambda item: (-item["symptom_hits"], -item["score"], item.get("code") or ""))
    return ranked
