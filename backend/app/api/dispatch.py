from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from loguru import logger
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.models.user import User, UserRole

router = APIRouter(prefix="/api/v1/dispatch", tags=["派工管理"])


class DispatchConfirmRequest(BaseModel):
    """派工确认请求 - 推荐验证 + 创建工单 合成事务"""
    fault_description: str
    technician_id: int
    device_id: Optional[int] = None
    device_code: Optional[str] = None
    fault_code: Optional[str] = None
    priority: str = "MEDIUM"
    location: Optional[str] = None
    tags: Optional[List[str]] = None
    fault_category: Optional[str] = None
    fault_phenomenon_type: Optional[str] = None
    fault_phenomenon: Optional[str] = None


class DispatchConfirmResponse(BaseModel):
    success: bool
    work_order_id: Optional[int] = None
    work_order_no: Optional[str] = None
    technician_name: Optional[str] = None
    error: Optional[str] = None


class DispatchBindRequest(BaseModel):
    """给已有汽修工单绑定技师和工位，不改变状态机。"""
    work_order_id: int
    technician_id: int
    bay_id: Optional[int] = None


@router.get("/technicians", summary="获取所有可用维修员列表(主管派工下拉)")
def list_technicians(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in (UserRole.SUPERVISOR.value, UserRole.ADMIN.value):
        raise HTTPException(status_code=403, detail="仅主管或管理员可查看维修员列表")

    technicians = (
        db.query(User)
        .filter(User.role == UserRole.TECHNICIAN.value)
        .filter(User.is_active == True)
        .order_by(User.current_workload_count.asc(), User.real_name.asc())
        .all()
    )

    # 近7天已完成工单数：一次聚合查询避免 N+1
    from datetime import datetime, timedelta
    from sqlalchemy import func
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    completed_count_rows = (
        db.query(
            WorkOrder.technician_id,
            func.count(WorkOrder.id).label("cnt")
        )
        .filter(WorkOrder.status == "COMPLETED")
        .filter(WorkOrder.updated_at >= seven_days_ago)
        .group_by(WorkOrder.technician_id)
        .all()
    )
    completed_map = {row.technician_id: row.cnt for row in completed_count_rows if row.technician_id}

    result = []
    for t in technicians:
        result.append({
            "id": t.id,
            "real_name": t.real_name,
            "username": t.username,
            "employee_id": t.employee_id,
            "role": t.role,
            "phone": t.phone,
            "skills_json": t.skills_json,
            "current_workload_count": t.current_workload_count or 0,
            "last_online_at": t.last_online_at,
            "skills": t.skills,
            "recent7d_completed": completed_map.get(t.id, 0),
        })
    return result


@router.post("/confirm", response_model=DispatchConfirmResponse, summary="派工确认（推荐+创建工单 合成事务）")
def confirm_dispatch(
    data: DispatchConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """主管确认派工：验证维修员 → 在岗校验 → 创建工单 → 钉钉推送，一个事务完成"""
    if current_user.role not in (UserRole.SUPERVISOR.value, UserRole.ADMIN.value):
        raise HTTPException(status_code=403, detail="仅主管或管理员可确认派工")

    # 1. 验证维修员
    technician = db.query(User).filter(User.id == data.technician_id).first()
    if not technician:
        raise HTTPException(status_code=400, detail="指派的维修员不存在")
    if not technician.is_active:
        raise HTTPException(status_code=400, detail="指派的维修员已停用")
    if technician.role not in (UserRole.TECHNICIAN.value, UserRole.ADMIN.value):
        raise HTTPException(status_code=400, detail="被指派人必须是维修员角色")

    # 2. 在岗校验
    from app.models.duty_schedule import DutySchedule
    from datetime import datetime, date as date_type
    today = date_type.today()
    now_hour = datetime.now().hour
    today_schedules = db.query(DutySchedule).filter(
        DutySchedule.user_id == data.technician_id,
        DutySchedule.date == today,
    ).all()

    for s in today_schedules:
        if s.schedule_type == 'LEAVE' and s.shift == 'ALL_DAY':
            raise HTTPException(status_code=400, detail=f"该维修员今日全天请假，无法派工")

    # 当前时段请假校验（与 duty_schedules.SHIFT_HOURS 保持一致：早班 8-16、中班 16-24、晚班 0-8）
    def _current_shift(hour):
        if 8 <= hour < 16: return "MORNING"
        if 16 <= hour < 24: return "AFTERNOON"
        return "NIGHT"

    cur_shift = _current_shift(now_hour)
    for s in today_schedules:
        if s.schedule_type == 'LEAVE' and s.shift == cur_shift:
            raise HTTPException(status_code=400, detail=f"该维修员当前时段请假（{cur_shift}），无法派工")

    # 3. 生成工单号
    today_str = today.strftime("%Y%m%d")
    prefix = f"WO-{today_str}-"
    latest = (
        db.query(WorkOrder)
        .filter(WorkOrder.work_order_no.like(f"{prefix}%"))
        .order_by(WorkOrder.work_order_no.desc())
        .first()
    )
    if latest and latest.work_order_no:
        try:
            seq = int(latest.work_order_no.split("-")[-1]) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1
    work_order_no = f"{prefix}{seq:03d}"

    # 4. 创建工单
    work_order = WorkOrder(
        work_order_no=work_order_no,
        device_id=data.device_id,
        device_code=data.device_code,
        fault_code=data.fault_code,
        fault_description=data.fault_description,
        fault_category=data.fault_category,
        fault_phenomenon_type=data.fault_phenomenon_type,
        fault_phenomenon=data.fault_phenomenon,
        priority=data.priority or "MEDIUM",
        location=data.location,
        technician_id=data.technician_id,
        assignee_id=data.technician_id,
        tags=data.tags,
        status=WorkOrderStatus.ASSIGNED,
        created_by=current_user.id,
    )
    db.add(work_order)
    db.flush()

    # 5. 记录进度日志
    from app.api.work_orders import _add_progress_log, _update_workload
    _add_progress_log(
        db=db,
        work_order_id=work_order.id,
        from_status=WorkOrderStatus.DRAFT,
        to_status=WorkOrderStatus.ASSIGNED,
        operator_id=current_user.id,
        operator_name=current_user.real_name,
        source="WEB",
        remark=f"主管派工，指派给 {technician.real_name}",
    )
    _update_workload(db, data.technician_id, +1)

    # 6. 钉钉推送（失败不影响工单创建）：发送带进度确认按钮的互动卡片
    try:
        from app.core.dingtalk_wo_card import send_progress_card
        from app.core.config import settings
        public_url = getattr(settings, "SERVER_PUBLIC_URL", "") or ""
        send_progress_card(
            technician.dingtalk_userid or "",
            work_order,
            supervisor_name=current_user.real_name,
            public_url=public_url,
        )
    except Exception as e:
        logger.warning(f"[Dispatch] 派工进度卡片发送失败（不影响工单创建）: {e}")

    db.commit()
    db.refresh(work_order)
    logger.info(f"[Dispatch] 派工确认成功: {work_order_no} → {technician.real_name}, operator={current_user.id}")

    return DispatchConfirmResponse(
        success=True,
        work_order_id=work_order.id,
        work_order_no=work_order_no,
        technician_name=technician.real_name,
    )


@router.post("/bind", summary="汽修工单绑定技师和工位")
def bind_dispatch(
    data: DispatchBindRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """复用派工的技师校验和钉钉卡片。只改技师/工位，状态仍由 /transition 推进。"""
    if current_user.role not in (UserRole.SUPERVISOR.value, UserRole.ADMIN.value):
        raise HTTPException(status_code=403, detail="仅主管或管理员可派工")

    work_order = db.query(WorkOrder).filter(WorkOrder.id == data.work_order_id).first()
    if not work_order:
        raise HTTPException(status_code=404, detail="工单不存在")
    from app.domain.work_order_status import is_auto_repair_lane
    if not is_auto_repair_lane(
        status=work_order.status,
        vehicle_id=work_order.vehicle_id,
        appointment_id=work_order.appointment_id,
        store_id=work_order.store_id,
    ):
        raise HTTPException(status_code=400, detail="仅汽修工单在此绑定技师和工位，工业派工请使用派工确认")
    if work_order.status and work_order.status.value in ("CLOSED", "CANCELLED", "ARCHIVED", "COMPLETED"):
        raise HTTPException(status_code=400, detail="工单已结束，不能改派")

    technician = db.query(User).filter(User.id == data.technician_id).first()
    if not technician or not technician.is_active:
        raise HTTPException(status_code=400, detail="指派的维修员不存在或已停用")
    if technician.role not in (UserRole.TECHNICIAN.value, UserRole.ADMIN.value):
        raise HTTPException(status_code=400, detail="被指派人必须是维修员角色")

    if data.bay_id is not None:
        from app.models.store import Bay
        bay = db.query(Bay).filter(Bay.id == data.bay_id).first()
        if not bay:
            raise HTTPException(status_code=400, detail="工位不存在")
        if work_order.store_id and bay.store_id != work_order.store_id:
            raise HTTPException(status_code=400, detail="工位不属于该门店")
        work_order.bay_id = bay.id
        if not work_order.store_id:
            work_order.store_id = bay.store_id

    from app.api.work_orders import _add_progress_log, _update_workload
    old_id = work_order.technician_id
    active = work_order.status and work_order.status.value not in ("CLOSED", "CANCELLED", "COMPLETED", "ARCHIVED", "REJECTED")
    if active and old_id and old_id != technician.id:
        _update_workload(db, old_id, -1)
    work_order.technician_id = technician.id
    work_order.assignee_id = technician.id
    if active and old_id != technician.id:
        _update_workload(db, technician.id, +1)

    status_enum = work_order.status
    _add_progress_log(
        db=db,
        work_order_id=work_order.id,
        from_status=status_enum,
        to_status=status_enum,
        operator_id=current_user.id,
        operator_name=current_user.real_name,
        source="WEB",
        remark=f"绑定技师 {technician.real_name}" + (f"，工位 #{work_order.bay_id}" if work_order.bay_id else ""),
    )
    try:
        from app.core.dingtalk_wo_card import send_progress_card
        from app.core.config import settings
        public_url = getattr(settings, "SERVER_PUBLIC_URL", "") or ""
        send_progress_card(
            technician.dingtalk_userid or "",
            work_order,
            supervisor_name=current_user.real_name,
            public_url=public_url,
        )
    except Exception as e:
        logger.warning(f"[Dispatch] 绑定后钉钉卡片发送失败（不影响派工）: {e}")

    db.commit()
    db.refresh(work_order)
    return {
        "success": True,
        "work_order_id": work_order.id,
        "work_order_no": work_order.work_order_no,
        "technician_id": technician.id,
        "technician_name": technician.real_name,
        "bay_id": work_order.bay_id,
        "status": work_order.status.value if work_order.status else None,
    }
