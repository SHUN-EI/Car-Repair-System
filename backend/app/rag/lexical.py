"""知识库关键词检索用的分词与 tsquery 构造。

不依赖 zhparser / pg_jieba：用与历史 ILIKE 路相同的规则，把中文 2/3-gram、
完整中文片段，以及长度不少于 2 的英文或数字记号交给 PostgreSQL `simple` 词典。
查询侧与库内 `repair_text_tokens()` 必须保持同一套规则，否则召回会对不齐。
"""
from __future__ import annotations

import re
from typing import Iterable, List, Sequence

_CHINESE_SPAN = re.compile(r"[一-鿿]+")
_TSQUERY_SAFE = re.compile(r"[^0-9A-Za-z一-鿿]+")


def tokenize_repair_text(text: str) -> List[str]:
    """把一段文本拆成检索记号：中文 2/3-gram 与整段，外加英文或数字词。

    Args:
        text: 标题、正文、故障码或查询原文，空值按空串处理。

    Returns:
        去重且保持出现顺序的记号列表；无法分出记号时返回空列表。
    """
    raw = (text or "").strip()
    if not raw:
        return []

    tokens: List[str] = []
    seen = set()

    def _add(token: str) -> None:
        if token and token not in seen:
            seen.add(token)
            tokens.append(token)

    for span in _CHINESE_SPAN.findall(raw):
        _add(span)
        for i in range(len(span)):
            for n in (2, 3):
                if i + n <= len(span):
                    _add(span[i:i + n])

    non_chinese = _CHINESE_SPAN.sub(" ", raw)
    for word in non_chinese.split():
        if len(word) >= 2:
            _add(word)
    return tokens


def escape_tsquery_term(term: str) -> str:
    """去掉 tsquery 特殊字符，避免用户输入破坏查询语法。"""
    cleaned = _TSQUERY_SAFE.sub("", term or "")
    return cleaned


def tokens_to_or_tsquery(tokens: Sequence[str]) -> str:
    """把记号连成 OR tsquery（`simple` 词典）。空输入返回空串。"""
    parts = []
    for token in tokens:
        safe = escape_tsquery_term(token)
        if safe:
            parts.append(safe)
    return " | ".join(parts)


def build_or_tsquery(text: str) -> str:
    """对原始查询分词并生成 OR tsquery 字符串。"""
    return tokens_to_or_tsquery(tokenize_repair_text(text))


def cosine_distance_to_similarity(distance: float) -> float:
    """把 pgvector 余弦距离（`<=>`）转成与历史 Milvus COSINE 分同一刻度的相似度。

    相似度 = 1 - 距离。L2 归一化向量下，该值与原先 `hit.score` 同量纲，
    现有粗筛和向量阈值可继续沿用，不要把距离原样送进阀门。
    """
    try:
        sim = 1.0 - float(distance)
    except (TypeError, ValueError):
        return 0.0
    if sim < 0:
        return 0.0
    if sim > 1:
        return 1.0
    return sim


def knowledge_point_id(knowledge_id: int) -> str:
    """知识条目在检索结果里使用的稳定向量点号，兼容原 milvus_id 字段。"""
    return f"pg:k:{knowledge_id}"


def manual_point_id(manual_code_id: int) -> str:
    """手册错误码条目的稳定向量点号。"""
    return f"pg:m:{manual_code_id}"


def parse_point_id(point_id: str) -> tuple[str, int] | None:
    """解析 `pg:k:12` / `pg:m:3` 形式的点号。无法识别时返回 None。"""
    if not point_id or not isinstance(point_id, str):
        return None
    for kind, prefix in (("knowledge", "pg:k:"), ("manual", "pg:m:")):
        if point_id.startswith(prefix):
            rest = point_id[len(prefix):]
            if rest.isdigit():
                return kind, int(rest)
    return None
