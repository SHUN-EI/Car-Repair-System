from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional, List
from loguru import logger

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.notification import notification_service
from app.core.cache_service import cache_service
from app.agents.inventory_tools import format_compatible_text, list_compatible_parts, resolve_fitment_spec
from app.domain.fitment import normalize_fitment, spec_is_empty
from app.domain.stock_ledger import StockError, apply_stock_delta
from app.domain.store_scope import StoreScopeError, ensure_writable_store, resolve_store_scope, row_in_scope
from app.models.spare_part import SparePart
from app.models.stock import StorePartStock
from app.models.user import User
from sqlalchemy import or_
from app.schemas import SparePartCreate, SparePartUpdate, SparePartResponse, PaginatedResponse

router = APIRouter()


def _sp_to_dict(s: SparePart) -> dict:
    data = {c.name: getattr(s, c.name) for c in s.__table__.columns}
    if data.get("fitment") is not None:
        try:
            data["fitment"] = normalize_fitment(data["fitment"])
        except ValueError:
            data["fitment"] = data["fitment"]
    return data


def _requested_store(store_id: Optional[int], x_store_id: Optional[str]) -> Optional[int]:
    if store_id:
        return store_id
    if x_store_id and str(x_store_id).strip().isdigit():
        return int(str(x_store_id).strip())
    return None


def _part_scope(user: User, store_id: Optional[int] = None, x_store_id: Optional[str] = None):
    try:
        return resolve_store_scope(user, _requested_store(store_id, x_store_id))
    except StoreScopeError as exc:
        raise HTTPException(status_code=403, detail=exc.message)


def _scope_part_query(query, db: Session, scope):
    if scope.mode == "legacy":
        return query.filter(SparePart.store_id.is_(None))
    if scope.mode == "store":
        stock_ids = db.query(StorePartStock.spare_part_id).filter(StorePartStock.store_id == scope.store_id)
        return query.filter(or_(SparePart.store_id == scope.store_id, SparePart.id.in_(stock_ids)))
    return query


def _stock_map(db: Session, part_ids, store_id: Optional[int]):
    if not part_ids or not store_id:
        return {}
    rows = (
        db.query(StorePartStock)
        .filter(StorePartStock.store_id == store_id, StorePartStock.spare_part_id.in_(part_ids))
        .all()
    )
    return {row.spare_part_id: row for row in rows}


def _present_part(part: SparePart, scope, stock_row=None) -> dict:
    data = _sp_to_dict(part)
    data["store_on_hand"] = stock_row.quantity if stock_row is not None else None
    if scope.mode == "store":
        if stock_row is not None:
            data["stock_quantity"] = stock_row.quantity
            data["store_on_hand"] = stock_row.quantity
        elif part.store_id == scope.store_id:
            data["store_on_hand"] = part.stock_quantity
    return data


def _part_visible(part: SparePart, scope, stock_row) -> bool:
    if scope.mode == "all":
        return True
    if scope.mode == "legacy":
        return part.store_id is None
    return part.store_id == scope.store_id or stock_row is not None


def _fitment_payload(data):
    payload = data.model_dump()
    if "fitment" in payload:
        try:
            payload["fitment"] = normalize_fitment(payload.get("fitment"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    return payload


# ==================== 进货单导入 Schema ====================
class PurchaseItem(BaseModel):
    part_code: str = Field(..., max_length=50)
    part_name: Optional[str] = None
    specification: Optional[str] = None
    unit: Optional[str] = "个"
    quantity: int = Field(..., gt=0, description="进货数量")
    unit_price: Optional[float] = 0.0
    device_type: Optional[str] = None
    location: Optional[str] = None
    supplier: Optional[str] = None
    safety_stock: Optional[int] = 0


class PurchaseImportRequest(BaseModel):
    items: List[PurchaseItem] = Field(..., min_length=1, max_length=200)
    store_id: Optional[int] = None


class PurchaseImportResult(BaseModel):
    total: int
    created: int = 0
    updated: int = 0
    skipped: int = 0
    details: List[dict] = []


# ==================== CRUD ====================

@router.get("/", response_model=PaginatedResponse[SparePartResponse], summary="获取备件列表")
def list_spare_parts(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    device_type: Optional[str] = None,
    keyword: Optional[str] = None,
    stock_status: Optional[str] = Query(None, description="low_stock / out_of_stock"),
    store_id: Optional[int] = None,
    x_store_id: Optional[str] = Header(None, alias="X-Store-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scope = _part_scope(current_user, store_id, x_store_id)
    query = _scope_part_query(db.query(SparePart), db, scope)
    if device_type:
        query = query.filter(SparePart.device_type == device_type)
    if keyword:
        query = query.filter(
            SparePart.part_name.ilike(f"%{keyword}%")
            | SparePart.part_code.ilike(f"%{keyword}%")
            | SparePart.specification.ilike(f"%{keyword}%")
        )
    if stock_status == "low_stock":
        query = query.filter(
            SparePart.stock_quantity > 0,
            SparePart.stock_quantity <= SparePart.safety_stock
        )
    elif stock_status == "out_of_stock":
        query = query.filter(SparePart.stock_quantity <= 0)

    total = query.count()
    items = query.order_by(SparePart.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    stocks = _stock_map(db, [item.id for item in items], scope.store_id)
    return {
        "total": total,
        "items": [_present_part(item, scope, stocks.get(item.id)) for item in items],
        "page": page,
        "page_size": page_size,
    }


@router.get("/alerts", summary="库存预警（带缓存）")
def get_stock_alerts(
    store_id: Optional[int] = None,
    x_store_id: Optional[str] = Header(None, alias="X-Store-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取低库存和缺货预警数据（缓存 30 秒）。店内角色看本店结存。"""
    scope = _part_scope(current_user, store_id, x_store_id)
    cache_key = f"stock_alerts:{scope.mode}:{scope.store_id or 'none'}"
    cached = cache_service.get(cache_key)
    if cached:
        return cached

    if scope.mode == "store":
        rows = (
            db.query(SparePart, StorePartStock)
            .join(StorePartStock, StorePartStock.spare_part_id == SparePart.id)
            .filter(StorePartStock.store_id == scope.store_id)
            .all()
        )
        low_stock = [(part, stock) for part, stock in rows if 0 < (stock.quantity or 0) <= (part.safety_stock or 0)]
        out_of_stock = [(part, stock) for part, stock in rows if (stock.quantity or 0) <= 0]
        low_items = [_present_part(part, scope, stock) for part, stock in low_stock]
        out_items = [_present_part(part, scope, stock) for part, stock in out_of_stock]
    else:
        query = _scope_part_query(db.query(SparePart), db, scope)
        low_parts = query.filter(
            SparePart.stock_quantity > 0,
            SparePart.stock_quantity <= SparePart.safety_stock,
        ).all()
        out_parts = _scope_part_query(db.query(SparePart), db, scope).filter(SparePart.stock_quantity <= 0).all()
        low_items = [_present_part(part, scope) for part in low_parts]
        out_items = [_present_part(part, scope) for part in out_parts]

    result = {
        "low_stock_count": len(low_items),
        "out_of_stock_count": len(out_items),
        "alert_count": len(low_items) + len(out_items),
        "low_stock_items": low_items,
        "out_of_stock_items": out_items,
    }
    cache_service.set(cache_key, result, ttl=30)
    return result


@router.post("/check-alerts", summary="手动触发库存预警检查")
def check_stock_alerts(db: Session = Depends(get_db)):
    """
    手动触发库存预警检查，发送钉钉通知
    返回预警结果
    """
    from app.core.stock_alert import check_and_notify_stock_alerts
    result = check_and_notify_stock_alerts(db)
    return result


@router.get("/compatible", summary="按车辆或车型查询适配备件")
def list_compatible(
    vehicle_id: Optional[int] = None,
    plate: Optional[str] = None,
    brand: Optional[str] = None,
    series: Optional[str] = None,
    year: Optional[int] = Query(None, ge=1900, le=2100),
    engine: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    store_id: Optional[int] = None,
    x_store_id: Optional[str] = Header(None, alias="X-Store-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """给定车辆或品牌/车系/年款/发动机，只返回 fitment 命中的备件和库存。"""
    spec, error = resolve_fitment_spec(
        db,
        vehicle_id=vehicle_id,
        plate=plate,
        brand=brand,
        series=series,
        year=year,
        engine=engine,
    )
    if error:
        raise HTTPException(status_code=404, detail=error)
    if spec_is_empty(spec):
        raise HTTPException(status_code=400, detail="请指定车辆，或提供品牌、车系、年款、发动机中的至少一项")
    parts = list_compatible_parts(
        db,
        brand=spec["brand"],
        series=spec["series"],
        year=spec["year"],
        engine=spec["engine"],
        keyword=keyword,
        limit=limit,
    )
    scope = _part_scope(current_user, store_id, x_store_id)
    stocks = _stock_map(db, [part.id for part in parts], scope.store_id)
    visible = [part for part in parts if _part_visible(part, scope, stocks.get(part.id))]
    items = [_present_part(part, scope, stocks.get(part.id)) for part in visible]
    if scope.mode == "store":
        lines = [f"适配备件 {len(items)} 条："]
        for item in items:
            lines.append(f"- {item['part_name']}（{item['part_code']}）本店库存 {item['stock_quantity']}{item.get('unit') or ''}")
        summary = "\n".join(lines) if items else format_compatible_text(spec, [])
    else:
        summary = format_compatible_text(spec, visible)
    return {
        "vehicle": spec,
        "total": len(items),
        "items": items,
        "summary": summary,
    }


@router.get("/{part_id}", response_model=SparePartResponse, summary="获取备件详情（带缓存）")
def get_spare_part(
    part_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scope = _part_scope(current_user)
    cache_key = f"spare_part:{part_id}"
    if scope.mode == "all":
        cached = cache_service.get(cache_key)
        if cached:
            return cached

    part = db.query(SparePart).filter(SparePart.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="备件不存在")
    stock_row = None
    if scope.store_id:
        stock_row = (
            db.query(StorePartStock)
            .filter(StorePartStock.store_id == scope.store_id, StorePartStock.spare_part_id == part.id)
            .first()
        )
    if not _part_visible(part, scope, stock_row):
        raise HTTPException(status_code=404, detail="备件不存在")

    result = _present_part(part, scope, stock_row)
    if scope.mode == "all":
        cache_service.set(cache_key, result, ttl=300)
    return result


@router.post("/", response_model=SparePartResponse, summary="创建备件")
def create_spare_part(
    data: SparePartCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = db.query(SparePart).filter(SparePart.part_code == data.part_code).first()
    if existing:
        raise HTTPException(status_code=400, detail="备件编码已存在")
    payload = _fitment_payload(data)
    try:
        stamped = ensure_writable_store(current_user, payload.get("store_id"))
    except StoreScopeError as exc:
        raise HTTPException(status_code=403, detail=exc.message)
    if stamped is not None:
        payload["store_id"] = stamped
    part = SparePart(**payload)
    db.add(part)
    db.commit()
    db.refresh(part)
    cache_service.invalidate_pattern("stock_alerts:*")
    return part


@router.put("/{part_id}", response_model=SparePartResponse, summary="更新备件")
def update_spare_part(part_id: int, data: SparePartUpdate, db: Session = Depends(get_db)):
    part = db.query(SparePart).filter(SparePart.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="备件不存在")
    changes = _fitment_payload(data)
    # model_dump 默认包含未传字段；这里只写客户端真正提交的键。
    sent = data.model_dump(exclude_unset=True)
    for key in list(changes):
        if key not in sent:
            changes.pop(key)
    for key, val in changes.items():
        setattr(part, key, val)
    db.commit()
    db.refresh(part)
    cache_service.delete(f"spare_part:{part_id}")
    cache_service.invalidate_pattern("stock_alerts:*")
    return part


@router.delete("/{part_id}", summary="删除备件")
def delete_spare_part(part_id: int, db: Session = Depends(get_db)):
    part = db.query(SparePart).filter(SparePart.id == part_id).first()
    if not part:
        raise HTTPException(status_code=404, detail="备件不存在")
    db.delete(part)
    db.commit()
    cache_service.delete(f"spare_part:{part_id}")
    cache_service.invalidate_pattern("stock_alerts:*")
    return {"message": "备件已删除"}


# ==================== 进货单批量导入 ====================

class SparePartIssueRequest(BaseModel):
    work_order_id: int
    part_code: str
    qty: int


@router.post("/issue", summary="在修工单领料出库")
def issue_spare_part(
    data: SparePartIssueRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """在修工单领用备件：立刻扣库存，并记到 used_parts。完工扣减会跳过已领出的行。"""
    from app.domain.work_order_status import parts_issue_allowed, status_value
    from app.models.work_order import WorkOrder

    if current_user.role == "SUPERVISOR":
        raise HTTPException(status_code=403, detail="主管仅可查看库存，领料请由维修员或管理员操作")
    code = (data.part_code or "").strip()
    if not code or data.qty <= 0:
        raise HTTPException(status_code=400, detail="请填写备件编码和大于 0 的数量")
    work_order = db.query(WorkOrder).filter(WorkOrder.id == data.work_order_id).first()
    if not work_order or not row_in_scope(resolve_store_scope(current_user), work_order.store_id):
        raise HTTPException(status_code=404, detail="工单不存在")
    if not parts_issue_allowed(work_order.status):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {status_value(work_order.status)} 不可领料",
        )
    spare = db.query(SparePart).filter(SparePart.part_code == code).first()
    if not spare:
        raise HTTPException(status_code=404, detail="备件不存在")
    try:
        apply_stock_delta(
            db,
            part=spare,
            qty_delta=-data.qty,
            movement_type="ISSUE",
            store_id=work_order.store_id,
            ref_type="work_order",
            ref_id=work_order.id,
            operator_id=current_user.id,
            note=f"工单领料 {work_order.work_order_no}",
        )
    except StockError as exc:
        raise HTTPException(status_code=400, detail=exc.message)
    used = list(work_order.used_parts or [])
    used.append({
        "name": spare.part_name,
        "code": spare.part_code,
        "qty": data.qty,
        "issued": True,
    })
    work_order.used_parts = used
    db.commit()
    cache_service.invalidate_pattern("stock_alerts:*")
    cache_service.delete(f"spare_part:{spare.id}")
    logger.info(
        f"[SpareParts] 领料 {spare.part_code} x{data.qty} → 工单 {work_order.work_order_no}，剩余 {spare.stock_quantity}"
    )
    return {
        "work_order_id": work_order.id,
        "part_code": spare.part_code,
        "part_name": spare.part_name,
        "qty": data.qty,
        "remaining_stock": spare.stock_quantity,
    }


@router.post("/import", response_model=PurchaseImportResult, summary="进货单批量导入")
def import_purchase_orders(
    req: PurchaseImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    批量导入备件：
    - 新备件（编码不存在）→ 自动创建
    - 已有备件（编码存在）→ 累加库存数量，更新单价和供应商
    带 store_id 时同时记门店结存和库存流水。
    """
    try:
        store_id = ensure_writable_store(current_user, req.store_id)
    except StoreScopeError as exc:
        raise HTTPException(status_code=403, detail=exc.message)
    result = PurchaseImportResult(total=len(req.items))
    details = []

    for item in req.items:
        existing = db.query(SparePart).filter(SparePart.part_code == item.part_code).first()

        if existing:
            part = existing
            if item.location:
                part.location = item.location
            if item.safety_stock > 0:
                part.safety_stock = item.safety_stock
            if item.part_name and not part.part_name:
                part.part_name = item.part_name
            if item.specification and not part.specification:
                part.specification = item.specification
            created = False
        else:
            part = SparePart(
                part_code=item.part_code,
                part_name=item.part_name or item.part_code,
                specification=item.specification,
                unit=item.unit or "个",
                stock_quantity=0,
                safety_stock=item.safety_stock or 0,
                unit_price=0,
                device_type=item.device_type,
                location=item.location,
                supplier=item.supplier,
                store_id=store_id,
            )
            db.add(part)
            db.flush()
            created = True
        try:
            apply_stock_delta(
                db,
                part=part,
                qty_delta=item.quantity,
                movement_type="IMPORT",
                store_id=store_id,
                ref_type="import",
                operator_id=current_user.id,
                note="进货单导入",
                unit_price=item.unit_price,
                supplier=item.supplier,
            )
        except StockError as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=exc.message)
        if created:
            result.created += 1
            details.append({"part_code": item.part_code, "action": "created", "quantity": item.quantity})
        else:
            result.updated += 1
            details.append({
                "part_code": item.part_code,
                "action": "updated",
                "quantity_added": item.quantity,
                "new_stock": part.stock_quantity,
            })

    db.commit()
    cache_service.invalidate_pattern("stock_alerts:*")
    logger.info(f"[SpareParts] 进货单导入完成: 共{result.total}项, 新建{result.created}, 更新{result.updated}")
    result.details = details
    return result
