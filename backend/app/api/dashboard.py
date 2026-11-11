"""Dashboard 聚合统计接口 — 一次请求返回所有统计数据"""
from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from sqlalchemy import cast, Date, func
from datetime import date
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app.domain.store_scope import apply_store_column, resolve_store_scope
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.models.knowledge import KnowledgeItem, KnowledgeStatus
from app.models.manual_code import ManualCodeEntry
from app.models.device import Device
from app.models.spare_part import SparePart
from app.models.user import User

router = APIRouter()


def _wo_to_dict(w: WorkOrder) -> dict:
    return {c.name: getattr(w, c.name) for c in w.__table__.columns}


@router.get("/stats", summary="Dashboard 聚合统计")
def dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    store_id: Optional[int] = None,
    x_store_id: Optional[str] = Header(None, alias="X-Store-Id"),
):
    """一次查询返回数据驾驶舱所需的所有统计数据。工单和备件按门店范围统计。"""
    today = date.today()
    requested = store_id
    if requested is None and x_store_id and str(x_store_id).strip().isdigit():
        requested = int(str(x_store_id).strip())
    scope = resolve_store_scope(current_user, requested)
    orders = apply_store_column(db.query(WorkOrder), WorkOrder.store_id, scope)
    parts = apply_store_column(db.query(SparePart), SparePart.store_id, scope)

    # 工单统计
    total_orders = orders.with_entities(func.count(WorkOrder.id)).scalar() or 0
    today_orders = orders.filter(
        cast(WorkOrder.created_at, Date) == today
    ).with_entities(func.count(WorkOrder.id)).scalar() or 0
    pending_review = orders.filter(
        WorkOrder.status == WorkOrderStatus.DRAFT
    ).with_entities(func.count(WorkOrder.id)).scalar() or 0

    # 知识统计
    total_knowledge = db.query(func.count(KnowledgeItem.id)).scalar() or 0
    published_knowledge = db.query(func.count(KnowledgeItem.id)).filter(
        KnowledgeItem.status == KnowledgeStatus.PUBLISHED
    ).scalar() or 0
    under_review_knowledge = db.query(func.count(KnowledgeItem.id)).filter(
        KnowledgeItem.status == KnowledgeStatus.UNDER_REVIEW
    ).scalar() or 0
    total_manual_codes = db.query(func.count(ManualCodeEntry.id)).scalar() or 0

    # 设备是全库台账（没有门店列）。备件按门店范围统计。
    total_devices = db.query(func.count(Device.id)).scalar() or 0
    total_spare_parts = parts.with_entities(func.count(SparePart.id)).scalar() or 0

    # 设备监控状态分布
    devices_all = db.query(Device.run_status, Device.fault_tags).all()
    device_monitor = {"online": 0, "offline": 0, "alarm": 0, "fault": 0, "unknown": 0,
                      "with_fault_tags": 0}
    for (s, ft) in devices_all:
        s_key = (s or "UNKNOWN").lower()
        if s_key not in device_monitor:
            s_key = "unknown"
        device_monitor[s_key] += 1
        if ft and len(ft) > 0:
            device_monitor["with_fault_tags"] += 1

    # 库存预警
    low_stock = parts.filter(
        SparePart.stock_quantity > 0,
        SparePart.stock_quantity <= SparePart.safety_stock
    ).all()
    out_of_stock = parts.filter(
        SparePart.stock_quantity <= 0
    ).all()
    stock_alert = len(low_stock) + len(out_of_stock)

    # 最近 6 条工单
    recent_orders = orders.order_by(
        WorkOrder.created_at.desc()
    ).limit(6).all()

    return {
        "total_orders": total_orders,
        "today_orders": today_orders,
        "pending_review": pending_review,
        "total_knowledge": total_knowledge,
        "total_manual_codes": total_manual_codes,
        "published_knowledge": published_knowledge,
        "under_review_knowledge": under_review_knowledge,
        "total_devices": total_devices,
        "total_spare_parts": total_spare_parts,
        "device_monitor": device_monitor,
        "stock_alert": stock_alert,
        "low_stock_items": [{c.name: getattr(s, c.name) for c in s.__table__.columns} for s in low_stock],
        "out_of_stock_items": [{c.name: getattr(s, c.name) for c in s.__table__.columns} for s in out_of_stock],
        "recent_orders": [_wo_to_dict(w) for w in recent_orders],
    }
