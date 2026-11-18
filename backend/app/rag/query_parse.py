"""问诊问句的浅层解析：抽出故障码，并把口语症状归到规范名。

不调用大模型。故障码复用现有 extract_error_codes；症状靠内置别名表，
再由图谱的 aliases 做补充合并。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Set

# 常见口语 → 规范名。图谱里的 aliases 会在检索时再补一层。
SYMPTOM_ALIASES = {
    "刹车有点紧": "刹车紧",
    "刹车发紧": "刹车紧",
    "刹车很紧": "刹车紧",
    "刹车紧": "刹车紧",
    "制动发紧": "刹车紧",
    "踏板发硬": "刹车紧",
    "热车怠速抖动": "怠速抖动",
    "怠速抖动": "怠速抖动",
    "怠速不稳": "怠速抖动",
    "车身抖动": "怠速抖动",
}


@dataclass
class ParsedConsultQuery:
    """问句解析结果：原始问句、故障码、规范症状名，以及用于图谱查找的键。"""
    query: str
    error_codes: List[str] = field(default_factory=list)
    symptoms: List[str] = field(default_factory=list)

    @property
    def canonical_keys(self) -> List[str]:
        """图谱查找用的规范名列表（症状 + 大写故障码）。"""
        keys = list(self.symptoms)
        for code in self.error_codes:
            if code and code not in keys:
                keys.append(code)
        return keys


_OBD_RE = re.compile(r"\b([PCBUpcbu][0-9A-Fa-f]{4})\b")


def normalize_obd_code(token: str) -> str:
    """把 OBD 码规范成大写，如 p0300 → P0300。"""
    return (token or "").strip().upper()


def extract_obd_codes(query: str) -> List[str]:
    """从问句中抽出 SAE 风格的 P/C/B/U 码，保持出现顺序且去重。"""
    found: List[str] = []
    seen: Set[str] = set()
    for match in _OBD_RE.finditer(query or ""):
        code = normalize_obd_code(match.group(1))
        if code not in seen:
            seen.add(code)
            found.append(code)
    return found


def extract_symptoms(query: str, extra_aliases: Optional[Iterable[tuple]] = None) -> List[str]:
    """按别名表从问句中识别症状规范名，长词优先，避免短词重复命中。"""
    text = query or ""
    mapping = dict(SYMPTOM_ALIASES)
    if extra_aliases:
        for alias, canonical in extra_aliases:
            if alias:
                mapping[str(alias)] = str(canonical)
    # 长词优先，避免「刹车紧」先吃掉「刹车有点紧」的前缀匹配问题：这里用子串包含，先排更长的别名
    symptoms: List[str] = []
    seen: Set[str] = set()
    for alias in sorted(mapping, key=len, reverse=True):
        if alias and alias in text:
            canonical = mapping[alias]
            if canonical not in seen:
                seen.add(canonical)
                symptoms.append(canonical)
    return symptoms


def parse_consult_query(
    query: str,
    *,
    existing_error_codes: Optional[Sequence[str]] = None,
    extra_aliases: Optional[Iterable[tuple]] = None,
) -> ParsedConsultQuery:
    """解析问句：合并现有错误码抽取结果与 OBD 形态，并识别症状规范名。

    Args:
        query: 店员输入的原句。
        existing_error_codes: 调用方已用 extract_error_codes 得到的码，避免重复扫描工业码规则。
        extra_aliases: 图谱里读出的 (别名, 规范名) 对。
    """
    codes: List[str] = []
    seen: Set[str] = set()

    def _add(code: str) -> None:
        token = (code or "").strip().upper()
        # 工业码抽取会去掉 OBD 中的分隔符，P0300 会保持 P0300；统一大写即可
        if token and token not in seen:
            seen.add(token)
            codes.append(token)

    if existing_error_codes is not None:
        for code in existing_error_codes:
            _add(code)
    else:
        from app.agents.tools import extract_error_codes
        for code in extract_error_codes(query):
            _add(code)
    for code in extract_obd_codes(query):
        _add(code)

    return ParsedConsultQuery(
        query=query or "",
        error_codes=codes,
        symptoms=extract_symptoms(query, extra_aliases=extra_aliases),
    )
