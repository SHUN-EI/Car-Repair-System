"""检索结果的来源类型、出处文案和融合时用到的方法常量。

生成层、前端标签和 RRF 关键词分归类都走这里，避免只认手册错误码 / 工单案例。
本模块不导入检索工具或数据库，便于单测。
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# 这些检索路给出的是关键词分（ts_rank 等），融合时按关键词路归一化，不能当成向量余弦分。
KEYWORD_SCORE_METHODS = frozenset({
    "bm25_search",
    "obd_keyword_search",
    "manual_chunk_keyword",
    "faq_keyword_search",
})

# 错误码精确命中：融合后必须保留并置顶，不因粗筛阈值被丢掉。
EXACT_METHODS = frozenset({
    "obd_code_exact",
    "manual_code_exact",
})

# 数字越小优先级越高。原厂手册与 OBD 最高，已审客服知识最低。
SOURCE_PRIORITY = {
    "OBD": 0,
    "OEM_MANUAL": 0,
    "TECH_MANUAL": 1,
    "MANUAL": 1,
    "CASE": 2,
    "FAQ": 3,
}

SOURCE_LABELS = {
    "OBD": "OBD",
    "OEM_MANUAL": "原厂手册",
    "TECH_MANUAL": "技术手册",
    "MANUAL": "手册",
    "CASE": "工单案例",
    "FAQ": "客服知识",
}


def infer_source_type(item: Dict) -> str:
    """从检索字典推断来源类型，优先用已有的 source_type。"""
    raw = (item.get("source_type") or "").strip().upper()
    if raw:
        return raw
    if item.get("manual_code_id") is not None:
        return "MANUAL"
    method = str(item.get("method") or "")
    if item.get("obd_id") is not None or method.startswith("obd_"):
        return "OBD"
    if item.get("chunk_id") is not None:
        return "OEM_MANUAL"
    if item.get("faq_id") is not None:
        return "FAQ"
    return "CASE"


def source_priority(item: Dict) -> int:
    """出处优先级，数字越小越权威。未知类型按工单案例处理。"""
    return SOURCE_PRIORITY.get(infer_source_type(item), 2)


def format_source_citation(item: Dict) -> Tuple[str, str]:
    """返回 (来源中文名, 出处补充，不含括号)。"""
    source_type = infer_source_type(item)
    label = SOURCE_LABELS.get(source_type, "工单案例")
    parts: List[str] = []
    if source_type == "OBD":
        standard = (item.get("standard") or "").strip()
        code = (item.get("error_code") or item.get("fault_code") or "").strip()
        if standard:
            parts.append(standard)
        if code:
            parts.append(code)
    elif source_type in {"OEM_MANUAL", "TECH_MANUAL", "MANUAL"}:
        for key in ("manual_name", "chapter", "page"):
            value = (item.get(key) or "").strip()
            if value:
                parts.append(value)
        code = (item.get("error_code") or item.get("fault_code") or "").strip()
        if source_type == "MANUAL" and code:
            parts.append(f"错误码 {code}")
    return label, "·".join(parts)


def format_source_line(item: Dict) -> str:
    """单行来源，例如「原厂手册（制动系统·第5章·5-12）」或「工单案例」。"""
    label, cite = format_source_citation(item)
    if cite:
        return f"{label}（{cite}）"
    return label


def format_case_for_prompt(
    item: Dict,
    index: int,
    *,
    content_limit: int = 800,
    style: str = "detailed",
) -> str:
    """把一条检索结果格式化成送给模型的参考文本，带来源标注。"""
    label = format_source_line(item)
    title = item.get("title") or ""
    score = item.get("score", 0) or 0
    content = (item.get("content") or "")[:content_limit]
    fault_code = item.get("fault_code") or item.get("error_code") or ""
    if style == "compact":
        return f"### 参考 {index}（来源: {label}）: {title}\n{content}\n\n"
    if style == "brief":
        return f"\n【参考{index}·{label}】{title}\n处理要点: {content}\n"
    return (
        f"\n### 参考 {index}（相关度: {score:.0%} · 来源: {label}）\n"
        f"- 标题: {title}\n"
        f"- 故障码: {fault_code}\n"
        f"- 内容: {content}\n"
    )


def pin_exact_hits(merged: Sequence[Dict], top_k: int) -> List[Dict]:
    """把 OBD / 手册错误码精确命中排到前面，再截断；精确命中条数超过 top_k 时仍全部保留。"""
    if not merged:
        return []
    exact = [item for item in merged if item.get("method") in EXACT_METHODS]
    rest = [item for item in merged if item.get("method") not in EXACT_METHODS]
    if len(exact) >= top_k:
        return list(exact)
    return exact + rest[: max(top_k - len(exact), 0)]
