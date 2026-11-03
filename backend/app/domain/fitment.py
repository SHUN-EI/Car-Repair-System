"""备件适配规则。

fitment 是 JSON 数组，每条规则：
brand / series / year_from / year_to / engine。
空字段表示这一维不限制。整条都空表示不限车型。
没有规则的备件不参与适配查询，避免把整仓都算成适配。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


_FITMENT_KEYS = ("brand", "series", "year_from", "year_to", "engine")
_QUESTION_HINTS = ("适配", "适用")
_ENGINE_RE = re.compile(r"\d\.\d\s*[TtLl]|[1-9]\d?[Tt]")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_PLATE_RE = re.compile(r"车牌[:：\s]*([A-Za-z0-9\u4e00-\u9fff]{5,8})")


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _norm(value: Any) -> str:
    return ("" if value is None else str(value)).strip().casefold()


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def iter_rules(fitment: Any) -> List[dict]:
    if not fitment:
        return []
    if isinstance(fitment, dict):
        raw = [fitment]
    elif isinstance(fitment, list):
        raw = fitment
    else:
        return []
    return [row for row in raw if isinstance(row, dict)]


def normalize_fitment(rules: Any) -> Optional[List[dict]]:
    """写入前整理规则。空列表存成 None。年款起大于年款止时抛 ValueError。"""
    if rules is None:
        return None
    if isinstance(rules, dict):
        rules = [rules]
    if not isinstance(rules, list):
        raise ValueError("适配规则必须是数组")
    cleaned: List[dict] = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("适配规则必须是对象")
        year_from = _as_int(rule.get("year_from"))
        year_to = _as_int(rule.get("year_to"))
        if year_from is not None and year_to is not None and year_from > year_to:
            raise ValueError("年款起不能大于年款止")
        cleaned.append({
            "brand": _clean_str(rule.get("brand")),
            "series": _clean_str(rule.get("series")),
            "year_from": year_from,
            "year_to": year_to,
            "engine": _clean_str(rule.get("engine")),
        })
    return cleaned or None


def rule_matches(
    rule: dict,
    *,
    brand: Any = None,
    series: Any = None,
    year: Any = None,
    engine: Any = None,
) -> bool:
    if _norm(rule.get("brand")) and _norm(rule.get("brand")) != _norm(brand):
        return False
    if _norm(rule.get("series")) and _norm(rule.get("series")) != _norm(series):
        return False
    year_from = _as_int(rule.get("year_from"))
    year_to = _as_int(rule.get("year_to"))
    vehicle_year = _as_int(year)
    if year_from is not None or year_to is not None:
        if vehicle_year is None:
            return False
        if year_from is not None and vehicle_year < year_from:
            return False
        if year_to is not None and vehicle_year > year_to:
            return False
    if _norm(rule.get("engine")) and _norm(rule.get("engine")) != _norm(engine):
        return False
    return True


def part_matches(fitment: Any, **vehicle) -> bool:
    rules = iter_rules(fitment)
    if not rules:
        return False
    return any(rule_matches(rule, **vehicle) for rule in rules)


def fitment_brief(fitment: Any, limit: int = 2) -> str:
    rules = iter_rules(fitment)
    if not rules:
        return ""
    parts: List[str] = []
    for rule in rules[:limit]:
        bits = [rule.get("brand") or "", rule.get("series") or ""]
        year_from = rule.get("year_from")
        year_to = rule.get("year_to")
        if year_from and year_to:
            bits.append(f"{year_from}-{year_to}")
        elif year_from:
            bits.append(f"{year_from}起")
        elif year_to:
            bits.append(f"至{year_to}")
        if rule.get("engine"):
            bits.append(str(rule["engine"]))
        text = " ".join(str(bit) for bit in bits if bit).strip()
        parts.append(text or "不限车型")
    text = "；".join(parts)
    if len(rules) > limit:
        text += f" 等{len(rules)}条"
    return text


def looks_like_fitment_question(text: str) -> bool:
    raw = text or ""
    return any(hint in raw for hint in _QUESTION_HINTS)


def parse_fitment_question(text: str) -> Dict[str, Any]:
    """从「大众 速腾 2018 1.4T 适配刹车片」这类问句里抽出车型。空格分隔更稳。"""
    raw = text or ""
    year = None
    year_match = _YEAR_RE.search(raw)
    if year_match:
        year = int(year_match.group(0))
        raw = raw[:year_match.start()] + " " + raw[year_match.end():]
    engine = ""
    engine_match = _ENGINE_RE.search(raw)
    if engine_match:
        engine = engine_match.group(0).replace(" ", "").upper()
        raw = raw[:engine_match.start()] + " " + raw[engine_match.end():]
    plate = ""
    plate_match = _PLATE_RE.search(raw)
    if plate_match:
        plate = plate_match.group(1).upper()
        raw = raw[:plate_match.start()] + " " + raw[plate_match.end():]
    for word in ("能不能", "请问", "一下", "哪些", "什么", "库存", "备件", "配件", "适配", "适用", "车型", "可以"):
        raw = raw.replace(word, " ")
    raw = re.sub(r"[的吗呢和与及、,，]", " ", raw)
    tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", raw)
    return {
        "brand": tokens[0] if tokens else "",
        "series": tokens[1] if len(tokens) > 1 else "",
        "keyword": "".join(tokens[2:]) if len(tokens) > 2 else "",
        "year": year,
        "engine": engine,
        "plate": plate,
    }


def spec_is_empty(spec: Dict[str, Any]) -> bool:
    return not any([
        _norm(spec.get("brand")),
        _norm(spec.get("series")),
        spec.get("year") is not None,
        _norm(spec.get("engine")),
    ])


def public_rule(rule: dict) -> dict:
    return {key: rule.get(key) for key in _FITMENT_KEYS}


def public_fitment(fitment: Any) -> Optional[List[dict]]:
    rules = iter_rules(fitment)
    if not rules:
        return None
    return [public_rule(rule) for rule in rules]
