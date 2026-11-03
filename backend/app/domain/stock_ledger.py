"""备件库存变动。

采购入库、批量导入和工单领料都走这里：
先改 spare_parts.stock_quantity（仓库页和预警沿用的总库存），
门店有 store_id 时再改该店的结存，并记一条库存流水。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.spare_part import SparePart
from app.models.stock import StockMovement, StorePartStock


class StockError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def apply_stock_delta(
    db: Session,
    *,
    part: SparePart,
    qty_delta: int,
    movement_type: str,
    store_id: Optional[int] = None,
    ref_type: Optional[str] = None,
    ref_id: Optional[int] = None,
    operator_id: Optional[int] = None,
    note: Optional[str] = None,
    unit_price: Optional[float] = None,
    supplier: Optional[str] = None,
) -> StockMovement:
    delta = int(qty_delta)
    if delta == 0:
        raise StockError("变动数量不能为 0")
    current = int(part.stock_quantity or 0)
    if current + delta < 0:
        raise StockError(f"库存不足，当前 {current}")
    store_row = None
    if store_id is not None:
        store_row = (
            db.query(StorePartStock)
            .filter(
                StorePartStock.store_id == store_id,
                StorePartStock.spare_part_id == part.id,
            )
            .first()
        )
        if store_row is None and delta < 0:
            store_row = None
        elif store_row is None:
            store_row = StorePartStock(store_id=store_id, spare_part_id=part.id, quantity=0)
            db.add(store_row)
            db.flush()
        if store_row is not None:
            store_qty = int(store_row.quantity or 0)
            if store_qty + delta < 0:
                raise StockError(f"本店库存不足，当前 {store_qty}")
            store_row.quantity = store_qty + delta
    part.stock_quantity = current + delta
    if unit_price is not None and unit_price > 0:
        part.unit_price = unit_price
    if supplier:
        part.supplier = supplier
    movement = StockMovement(
        store_id=store_id,
        spare_part_id=part.id,
        part_code=part.part_code,
        qty_delta=delta,
        movement_type=movement_type,
        ref_type=ref_type,
        ref_id=ref_id,
        balance_after=part.stock_quantity,
        store_balance_after=store_row.quantity if store_row is not None else None,
        operator_id=operator_id,
        note=note,
    )
    db.add(movement)
    db.flush()
    return movement
