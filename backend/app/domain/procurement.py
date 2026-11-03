"""采购单状态与入库数量。库存数字的落库在 stock_ledger。"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple

PO_STATUSES = ("ORDERED", "PARTIAL", "RECEIVED", "CANCELLED")


def po_status_after_receive(lines: Sequence[Tuple[int, int]]) -> str:
    """lines 是 (订购数量, 已收数量)。收齐为已入库，收过一部分为部分入库。"""
    if not lines:
        return "ORDERED"
    if all(received >= ordered and ordered > 0 for ordered, received in lines):
        return "RECEIVED"
    if any(received > 0 for _, received in lines):
        return "PARTIAL"
    return "ORDERED"


def receive_qty(ordered: int, already: int, requested: Optional[int]) -> int:
    """本次实收。不传数量时收剩余。不能超过未收数量。"""
    remaining = int(ordered) - int(already)
    if remaining <= 0:
        if requested is None:
            return 0
        raise ValueError("该行已全部入库")
    qty = remaining if requested is None else int(requested)
    if qty <= 0:
        raise ValueError("入库数量要大于 0")
    if qty > remaining:
        raise ValueError(f"入库数量超过未收数量 {remaining}")
    return qty


def next_po_no(existing_numbers: Iterable[str], day: str) -> str:
    prefix = f"PO-{day}-"
    seq = 0
    for number in existing_numbers:
        if not number or not str(number).startswith(prefix):
            continue
        try:
            seq = max(seq, int(str(number).split("-")[-1]))
        except ValueError:
            continue
    return f"{prefix}{seq + 1:03d}"
