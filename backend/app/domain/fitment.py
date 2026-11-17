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
    """把任意值转成去掉首尾空白的字符串；空值或全空白返回 None，避免把空串写进适配规则。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _norm(value: Any) -> str:
    """做大小写无关的比较用归一化：转字符串、去首尾空白并 casefold。None 视为空串。"""
    return ("" if value is None else str(value)).strip().casefold()


def _as_int(value: Any) -> Optional[int]:
    """把年份等字段安全转成整数；空值、空串或无法转换时返回 None，不抛异常。"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def iter_rules(fitment: Any) -> List[dict]:
    """把配件适配规则统一展开成字典列表。

    单条规则可以是一个 dict，多条规则是 list[dict]；空值或其它类型返回空列表，并丢掉非字典元素。
    """
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
    """判断一条适配规则是否匹配给定车辆。

    规则里填写了的品牌、车系、发动机必须一致（忽略大小写）；年份若设置了起止区间，车辆年份必须落在闭区间内，缺少年份则视为不匹配。规则中未填写的条件视为不限制。
    """
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
    """判断配件的全部适配规则中，是否至少有一条匹配当前车辆。没有任何规则时返回 False，避免「空规则被当成适配所有车型」。"""
    rules = iter_rules(fitment)
    if not rules:
        return False
    return any(rule_matches(rule, **vehicle) for rule in rules)


def fitment_brief(fitment: Any, limit: int = 2) -> str:
    """把适配规则压成简短中文说明，供列表或提示展示。

    默认最多展示 limit 条，每条由品牌、车系、年款区间和发动机拼接；规则条件全空时写「不限车型」。超出条数时追加「等N条」。
    """
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
    """用预置关键词粗判用户问题是不是在问「这配件适不适合某车型」，供咨询链路决定是否走适配查询。"""
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
    """判断车型规格是否四个关键字段都空：品牌、车系、年份、发动机都没有有效值时返回 True。"""
    return not any([
        _norm(spec.get("brand")),
        _norm(spec.get("series")),
        spec.get("year") is not None,
        _norm(spec.get("engine")),
    ])


def public_rule(rule: dict) -> dict:
    """只保留对外可展示的适配字段（_FITMENT_KEYS），去掉内部多余键后再返回。"""
    return {key: rule.get(key) for key in _FITMENT_KEYS}


def public_fitment(fitment: Any) -> Optional[List[dict]]:
    """把配件适配数据整理成对外可返回的规则列表；没有任何合法规则时返回 None 而不是空列表。"""
    rules = iter_rules(fitment)
    if not rules:
        return None
    return [public_rule(rule) for rule in rules]
