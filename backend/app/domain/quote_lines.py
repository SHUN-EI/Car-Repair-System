"""把工单领料、问诊建议和保养套餐收成报价明细。价格只来自目录，没有目录价就记 0，留给店员改。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


_SKIP_MARKS = ("知识库未给出", "未给出可执行项目")
_LINE_TYPES = {"PART", "LABOR", "PACKAGE"}


def _norm(value: Any) -> str:
    return ("" if value is None else str(value)).strip().casefold()


def parse_consult_items(text: Optional[str]) -> List[str]:
    """抽出问诊里的建议项目。明确写了「知识库未给出」的句子不进报价。"""
    if not text or not str(text).strip():
        return []
    body = str(text)
    marked = re.search(r"【建议项目】(.*?)(?:【|$)", body, re.S)
    if marked:
        body = marked.group(1)
    else:
        loose = re.search(
            r"建议项目[:：](.*?)(?:\n\s*(?:是否预约|风险提示|症状理解)|\Z)",
            body,
            re.S,
        )
        if loose:
            body = loose.group(1)
    items: List[str] = []
    seen = set()
    for chunk in re.split(r"[\n;；]+", body):
        line = re.sub(r"^[\s\d\.、\-•]+", "", chunk).strip()
        if not line or any(mark in line for mark in _SKIP_MARKS):
            continue
        line = line[:200]
        if line in seen:
            continue
        seen.add(line)
        items.append(line)
        if len(items) >= 12:
            break
    return items


def _money(qty: Any, unit_price: Any) -> Tuple[float, float, float]:
    quantity = float(qty or 0)
    price = float(unit_price or 0)
    if quantity < 0:
        quantity = 0
    if price < 0:
        price = 0
    return quantity, round(price, 2), round(quantity * price, 2)


def match_catalog(name: str, rows: Optional[List[dict]]) -> Optional[dict]:
    target = _norm(name)
    if not target or not rows:
        return None
    best = None
    best_len = 0
    for row in rows:
        code = _norm(row.get("code"))
        title = _norm(row.get("name"))
        if code and code == target:
            return row
        if title and title == target:
            return row
        if title and len(title) >= 2 and title in target and len(title) > best_len:
            best = row
            best_len = len(title)
    return best


def build_quote_lines(
    *,
    used_parts: Optional[List[dict]] = None,
    part_prices: Optional[dict] = None,
    part_catalog: Optional[List[dict]] = None,
    consult_text: Optional[str] = None,
    suggestions: Optional[List[dict]] = None,
    packages: Optional[List[dict]] = None,
    service_catalog: Optional[List[dict]] = None,
    include_used_parts: bool = True,
    include_packages: bool = False,
) -> Tuple[List[dict], str]:
    lines: List[dict] = []
    notes: List[str] = []
    prices = part_prices or {}

    def add(line_type: str, name: str, code: str, qty: Any, unit_price: Any, source: str, ref_id: Any = None) -> None:
        quantity, price, amount = _money(qty, unit_price)
        if quantity <= 0 or not (name or "").strip():
            return
        kind = line_type if line_type in _LINE_TYPES else "LABOR"
        lines.append({
            "line_type": kind,
            "name": name.strip()[:200],
            "code": (code or "")[:50] or None,
            "qty": quantity,
            "unit_price": price,
            "amount": amount,
            "source": source,
            "ref_id": ref_id,
        })

    if include_used_parts:
        for part in used_parts or []:
            if not isinstance(part, dict):
                continue
            code = str(part.get("code") or part.get("part_code") or "").strip()
            name = str(part.get("name") or part.get("part_name") or code or "配件").strip()
            price = part.get("unit_price")
            if price is None:
                price = prices.get(code, 0)
            add("PART", name, code, part.get("qty") or 1, price, "work_order", part.get("id"))

    consult_items = parse_consult_items(consult_text)
    if consult_text and str(consult_text).strip() and not consult_items and not suggestions:
        notes.append("问诊文本里没有可报价的建议项目")
    for item in consult_items:
        part = match_catalog(item, part_catalog)
        sku = None if part else match_catalog(item, service_catalog)
        if part:
            add("PART", part.get("name") or item, part.get("code") or "", 1, part.get("unit_price") or 0, "consult", part.get("id"))
        elif sku:
            add("LABOR", sku.get("name") or item, sku.get("code") or "", 1, sku.get("base_price") or 0, "consult", sku.get("id"))
        else:
            add("LABOR", item, "", 1, 0, "consult", None)

    for suggestion in suggestions or []:
        if not isinstance(suggestion, dict):
            continue
        name = str(suggestion.get("name") or "").strip()
        if not name:
            continue
        code = str(suggestion.get("code") or "").strip()
        part = match_catalog(code or name, part_catalog)
        sku = None if part else match_catalog(code or name, service_catalog)
        price = suggestion.get("unit_price")
        line_type = str(suggestion.get("line_type") or "").upper()
        ref_id = suggestion.get("ref_id")
        if price is None and part:
            price = part.get("unit_price") or 0
            code = code or (part.get("code") or "")
            ref_id = ref_id or part.get("id")
            line_type = line_type or "PART"
        elif price is None and sku:
            price = sku.get("base_price") or 0
            code = code or (sku.get("code") or "")
            ref_id = ref_id or sku.get("id")
            line_type = line_type or "LABOR"
        elif price is None:
            price = 0
        if not line_type:
            line_type = "PART" if code else "LABOR"
        add(line_type, name, code, suggestion.get("qty") or 1, price, "consult", ref_id)

    if include_packages:
        chosen = list(packages or [])[:3]
        if not chosen:
            notes.append("没有符合该车型或里程的保养套餐")
        elif len(packages or []) > 3:
            notes.append("保养套餐只取排序前 3 个写入报价")
        for package in chosen:
            add(
                "PACKAGE",
                package.get("name") or "保养套餐",
                package.get("code") or "",
                1,
                package.get("list_price") or 0,
                "package",
                package.get("id"),
            )
            contained = [
                str(sku.get("name"))
                for sku in (service_catalog or [])
                if sku.get("package_id") and package.get("id") and sku.get("package_id") == package.get("id") and sku.get("name")
            ]
            if contained:
                notes.append(f"{package.get('name') or package.get('code')}含：" + "、".join(contained[:8]))

    for index, line in enumerate(lines, start=1):
        line["line_no"] = index
    return lines, "；".join(notes)
