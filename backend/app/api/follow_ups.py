"""回访 / 评价提醒。排期后由手动任务或定时任务发送。"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.domain.follow_up import (
    FOLLOW_UP_KINDS,
    KIND_LABELS,
    dispatch_due,
    schedule_reminder,
)
from app.domain.store_scope import (
    StoreScopeError,
    apply_store_column,
    ensure_writable_store,
    resolve_store_scope,
    row_in_scope,
)
from app.models.follow_up import FollowUpReminder
from app.models.user import User
from app.models.work_order import WorkOrder

router = APIRouter()


class FollowUpCreate(BaseModel):
    """创建回访或评价提醒的请求：关联工单、类型（回访/评价），以及可选的计划时间和备注。"""
    work_order_id: int
    kind: str = Field(..., description="REVISIT 回访 / RATING 评价")
    scheduled_at: Optional[datetime] = None
    note: Optional[str] = None


class FollowUpResponse(BaseModel):
    """回访提醒的接口返回，包含工单号、类型中文、发送结果和计划时间。"""
    id: int
    store_id: Optional[int] = None
    work_order_id: int
    work_order_no: Optional[str] = None
    customer_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    kind: str
    kind_label: str
    status: str
    scheduled_at: datetime
    sent_at: Optional[datetime] = None
    channel_result: Optional[dict] = None
    note: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


def _to_response(row: FollowUpReminder, work_order_no: Optional[str] = None) -> FollowUpResponse:
    """把提醒记录转成接口返回，并补上工单号和类型中文标签。"""
    return FollowUpResponse(
        id=row.id,
        store_id=row.store_id,
        work_order_id=row.work_order_id,
        work_order_no=work_order_no,
        customer_id=row.customer_id,
        vehicle_id=row.vehicle_id,
        kind=row.kind,
        kind_label=KIND_LABELS.get(row.kind, row.kind),
        status=row.status,
        scheduled_at=row.scheduled_at,
        sent_at=row.sent_at,
        channel_result=row.channel_result,
        note=row.note,
        created_at=row.created_at,
    )


def requested_store_id(
    store_id: Optional[int] = Query(None),
    x_store_id: Optional[str] = Header(None, alias="X-Store-Id"),
) -> Optional[int]:
    """从查询参数或请求头 X-Store-Id 取出要筛选的门店 ID。"""
    if store_id:
        return store_id
    if x_store_id and str(x_store_id).strip().isdigit():
        return int(str(x_store_id).strip())
    return None


def _scope(user: User, requested: Optional[int]):
    """解析当前用户的门店范围，范围不合法时转成 403。"""
    try:
        return resolve_store_scope(user, requested)
    except StoreScopeError as exc:
        raise HTTPException(status_code=403, detail=exc.message)


@router.get("/", summary="回访提醒列表")
def list_follow_ups(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    kind: Optional[str] = None,
    requested: Optional[int] = Depends(requested_store_id),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """按门店范围分页列出回访/评价提醒，可再按状态和类型过滤，按计划时间倒序。"""
    scope = _scope(current_user, requested)
    query = db.query(FollowUpReminder)
    query = apply_store_column(query, FollowUpReminder.store_id, scope)
    if status:
        query = query.filter(FollowUpReminder.status == status.strip().upper())
    if kind:
        query = query.filter(FollowUpReminder.kind == kind.strip().upper())
    total = query.count()
    rows = (
        query.order_by(FollowUpReminder.scheduled_at.desc(), FollowUpReminder.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    nos = {}
    ids = {row.work_order_id for row in rows}
    if ids:
        for wo_id, wo_no in db.query(WorkOrder.id, WorkOrder.work_order_no).filter(WorkOrder.id.in_(ids)).all():
            nos[wo_id] = wo_no
    return {
        "total": total,
        "items": [_to_response(row, nos.get(row.work_order_id)) for row in rows],
        "page": page,
        "page_size": page_size,
    }


@router.post("/", response_model=FollowUpResponse, summary="排期回访或评价提醒")
def create_follow_up(
    data: FollowUpCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """门店人员为指定工单排期一条回访或评价提醒。工单必须在当前门店可写范围内，类型只能是回访或评价。"""
    if current_user.role not in ("ADMIN", "SUPERVISOR", "TECHNICIAN"):
        raise HTTPException(status_code=403, detail="仅门店人员可排期提醒")
    work_order = db.query(WorkOrder).filter(WorkOrder.id == data.work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="工单不存在")
    scope = _scope(current_user, None)
    if not row_in_scope(scope, work_order.store_id):
        raise HTTPException(status_code=404, detail="工单不存在")
    try:
        store_id = ensure_writable_store(current_user, work_order.store_id)
    except StoreScopeError as exc:
        raise HTTPException(status_code=403, detail=exc.message)
    kind = data.kind.strip().upper()
    if kind not in FOLLOW_UP_KINDS:
        raise HTTPException(status_code=400, detail="提醒类型只能是回访或评价")
    when = data.scheduled_at or datetime.utcnow()
    try:
        row = schedule_reminder(
            db,
            work_order_id=work_order.id,
            kind=kind,
            scheduled_at=when,
            store_id=store_id if store_id is not None else work_order.store_id,
            customer_id=work_order.customer_id,
            vehicle_id=work_order.vehicle_id,
            note=data.note,
            created_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    db.refresh(row)
    return _to_response(row, work_order.work_order_no)


@router.post("/dispatch", summary="发送已到期的提醒")
def dispatch_follow_ups(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """主管或管理员立即发送所有已到期的提醒，返回发送结果。"""
    if current_user.role not in ("ADMIN", "SUPERVISOR"):
        raise HTTPException(status_code=403, detail="仅主管或管理员可发送到期提醒")
    return dispatch_due(db)


@router.post("/{reminder_id}/cancel", response_model=FollowUpResponse, summary="取消未发送的提醒")
def cancel_follow_up(
    reminder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """门店人员取消仍待发送的提醒。不在范围内或不存在时按 404 处理；已发送的不能取消。"""
    if current_user.role not in ("ADMIN", "SUPERVISOR", "TECHNICIAN"):
        raise HTTPException(status_code=403, detail="仅门店人员可取消提醒")
    row = db.query(FollowUpReminder).filter(FollowUpReminder.id == reminder_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="提醒不存在")
    scope = _scope(current_user, None)
    if not row_in_scope(scope, row.store_id):
        raise HTTPException(status_code=404, detail="提醒不存在")
    if row.status != "SCHEDULED":
        raise HTTPException(status_code=400, detail="只有待发送的提醒可以取消")
    row.status = "CANCELLED"
    db.commit()
    db.refresh(row)
    wo_no = db.query(WorkOrder.work_order_no).filter(WorkOrder.id == row.work_order_id).scalar()
    return _to_response(row, wo_no)
