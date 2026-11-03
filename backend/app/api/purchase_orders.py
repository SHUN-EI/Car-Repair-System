"""备件采购单：开单、入库、取消。入库同时写总库存、门店结存和库存流水。"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.cache_service import cache_service
from app.core.database import get_db
from app.core.security import get_current_user
from app.domain.procurement import next_po_no, po_status_after_receive, receive_qty
from app.domain.stock_ledger import StockError, apply_stock_delta
from app.domain.store_scope import (
    StoreScopeError,
    apply_store_column,
    ensure_writable_store,
    resolve_store_scope,
    row_in_scope,
)
from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.models.spare_part import SparePart
from app.models.store import Store
from app.models.user import User

router = APIRouter()


class PurchaseLineIn(BaseModel):
    part_code: str = Field(..., max_length=50)
    part_name: Optional[str] = Field(None, max_length=200)
    qty: int = Field(..., gt=0)
    unit_price: Optional[float] = 0


class PurchaseOrderCreate(BaseModel):
    store_id: int
    supplier: Optional[str] = None
    note: Optional[str] = None
    lines: List[PurchaseLineIn] = Field(..., min_length=1, max_length=100)


class ReceiveLineIn(BaseModel):
    line_id: int
    qty: Optional[int] = Field(None, gt=0)


class ReceiveRequest(BaseModel):
    lines: Optional[List[ReceiveLineIn]] = None


def requested_store_id(
    store_id: Optional[int] = Query(None),
    x_store_id: Optional[str] = Header(None, alias="X-Store-Id"),
) -> Optional[int]:
    if store_id:
        return store_id
    if x_store_id and str(x_store_id).strip().isdigit():
        return int(str(x_store_id).strip())
    return None


def _staff(user: User) -> bool:
    return user.role in ("ADMIN", "SUPERVISOR", "TECHNICIAN")


def _scope(user: User, requested: Optional[int]):
    try:
        return resolve_store_scope(user, requested)
    except StoreScopeError as exc:
        raise HTTPException(status_code=403, detail=exc.message)


def _line_out(line: PurchaseOrderLine) -> dict:
    return {
        "id": line.id,
        "spare_part_id": line.spare_part_id,
        "part_code": line.part_code,
        "part_name": line.part_name,
        "qty_ordered": line.qty_ordered,
        "qty_received": line.qty_received,
        "unit_price": line.unit_price,
    }


def _order_out(order: PurchaseOrder) -> dict:
    return {
        "id": order.id,
        "po_no": order.po_no,
        "store_id": order.store_id,
        "supplier": order.supplier,
        "status": order.status,
        "note": order.note,
        "created_by": order.created_by,
        "lines": [_line_out(line) for line in order.lines or []],
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


def _get_order(db: Session, order_id: int) -> PurchaseOrder:
    row = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="采购单不存在")
    return row


def _visible(user: User, order: PurchaseOrder):
    scope = _scope(user, None)
    if not row_in_scope(scope, order.store_id):
        raise HTTPException(status_code=404, detail="采购单不存在")


def _find_or_create_part(db: Session, line: PurchaseOrderLine, store_id: int, supplier: Optional[str]) -> SparePart:
    part = None
    if line.spare_part_id:
        part = db.query(SparePart).filter(SparePart.id == line.spare_part_id).first()
    if part is None:
        part = db.query(SparePart).filter(SparePart.part_code == line.part_code).first()
    if part is None:
        part = SparePart(
            part_code=line.part_code,
            part_name=line.part_name or line.part_code,
            stock_quantity=0,
            unit_price=line.unit_price or 0,
            supplier=supplier,
            store_id=store_id,
        )
        db.add(part)
        db.flush()
    line.spare_part_id = part.id
    return part


@router.get("/", summary="采购单列表")
def list_purchase_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    requested: Optional[int] = Depends(requested_store_id),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scope = _scope(current_user, requested)
    query = apply_store_column(db.query(PurchaseOrder), PurchaseOrder.store_id, scope)
    if status:
        query = query.filter(PurchaseOrder.status == status.strip().upper())
    total = query.count()
    rows = (
        query.order_by(PurchaseOrder.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "items": [_order_out(row) for row in rows],
        "page": page,
        "page_size": page_size,
    }


@router.get("/{order_id}", summary="采购单详情")
def get_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = _get_order(db, order_id)
    _visible(current_user, order)
    return _order_out(order)


@router.post("/", summary="新建采购单")
def create_purchase_order(
    data: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _staff(current_user):
        raise HTTPException(status_code=403, detail="仅门店人员可开采购单")
    try:
        store_id = ensure_writable_store(current_user, data.store_id)
    except StoreScopeError as exc:
        raise HTTPException(status_code=403, detail=exc.message)
    if store_id is None:
        raise HTTPException(status_code=400, detail="请选择门店")
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=400, detail="门店不存在")
    day = datetime.utcnow().strftime("%Y%m%d")
    existing = [row[0] for row in db.query(PurchaseOrder.po_no).filter(PurchaseOrder.po_no.like(f"PO-{day}-%")).all()]
    order = PurchaseOrder(
        po_no=next_po_no(existing, day),
        store_id=store_id,
        supplier=(data.supplier or "").strip() or None,
        status="ORDERED",
        note=data.note,
        created_by=current_user.id,
    )
    db.add(order)
    db.flush()
    for item in data.lines:
        code = item.part_code.strip()
        if not code:
            raise HTTPException(status_code=400, detail="备件编码不能为空")
        part = db.query(SparePart).filter(SparePart.part_code == code).first()
        db.add(PurchaseOrderLine(
            purchase_order_id=order.id,
            spare_part_id=part.id if part else None,
            part_code=code,
            part_name=(item.part_name or (part.part_name if part else code)).strip(),
            qty_ordered=item.qty,
            qty_received=0,
            unit_price=item.unit_price or 0,
        ))
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.post("/{order_id}/receive", summary="采购入库")
def receive_purchase_order(
    order_id: int,
    data: ReceiveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _staff(current_user):
        raise HTTPException(status_code=403, detail="仅门店人员可入库")
    order = _get_order(db, order_id)
    _visible(current_user, order)
    if order.status in ("RECEIVED", "CANCELLED"):
        raise HTTPException(status_code=400, detail="该采购单不能再入库")
    by_id = {line.id: line for line in order.lines or []}
    if data.lines:
        plan = [(by_id.get(item.line_id), item.qty) for item in data.lines]
    else:
        plan = [(line, None) for line in order.lines or []]
    if not plan or any(line is None for line, _ in plan):
        raise HTTPException(status_code=400, detail="入库明细不存在")
    try:
        touched = 0
        for line, qty in plan:
            take = receive_qty(line.qty_ordered, line.qty_received, qty)
            if take == 0:
                continue
            touched += 1
            part = _find_or_create_part(db, line, order.store_id, order.supplier)
            apply_stock_delta(
                db,
                part=part,
                qty_delta=take,
                movement_type="PO_RECEIVE",
                store_id=order.store_id,
                ref_type="purchase_order",
                ref_id=order.id,
                operator_id=current_user.id,
                note=f"采购入库 {order.po_no}",
                unit_price=line.unit_price,
                supplier=order.supplier,
            )
            line.qty_received = int(line.qty_received or 0) + take
        if touched == 0:
            raise ValueError("没有可入库的数量")
        order.status = po_status_after_receive([
            (line.qty_ordered, line.qty_received) for line in order.lines
        ])
    except (ValueError, StockError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    db.refresh(order)
    cache_service.invalidate_pattern("stock_alerts:*")
    return _order_out(order)


@router.post("/{order_id}/cancel", summary="取消未入库的采购单")
def cancel_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("ADMIN", "SUPERVISOR"):
        raise HTTPException(status_code=403, detail="仅主管或管理员可取消采购单")
    order = _get_order(db, order_id)
    _visible(current_user, order)
    if any((line.qty_received or 0) > 0 for line in order.lines or []):
        raise HTTPException(status_code=400, detail="已有入库数量，不能取消")
    if order.status == "CANCELLED":
        return _order_out(order)
    order.status = "CANCELLED"
    db.commit()
    db.refresh(order)
    return _order_out(order)
