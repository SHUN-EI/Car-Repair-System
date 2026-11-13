"""工单状态流转领域服务。

承接原 app.api.work_orders._do_transition 及其状态迁移/持久化依赖，
供 API 层与钉钉卡片通道复用，切断 core → api 的反向依赖。

权限判断、状态机、进度日志、返回结构与下沉前保持一致。
转到 COMPLETED 时仍复用 API 模块中的 complete_work_order_internal
（知识收录/备件扣减依赖 knowledge API 私有去重，本批不下沉整条完成链路）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException
from loguru import logger
from sqlalchemy.orm import Session

from app.domain.store_scope import StoreScopeError, resolve_store_scope, row_in_scope
from app.domain.work_order_status import (
    VALID_TRANSITIONS,
    STATUS_LABELS,
    allowed_transitions,
    is_auto_repair_lane,
    status_value,
)
from app.models.progress_log import WorkOrderProgressLog
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.schemas import WorkOrderProgressLogResponse, WorkOrderResponse, WorkOrderTransition

# 与 API 模块下沉前的局部别名一致，避免改动函数体。
_allowed_transitions = allowed_transitions
_status_value = status_value


def _parse_store_header(store_id: Optional[int], x_store_id: Optional[str]) -> Optional[int]:
    if store_id:
        return store_id
    if x_store_id and str(x_store_id).strip().isdigit():
        return int(str(x_store_id).strip())
    return None


def _work_order_scope(current_user: User, store_id: Optional[int], x_store_id: Optional[str]):
    try:
        return resolve_store_scope(current_user, _parse_store_header(store_id, x_store_id))
    except StoreScopeError as exc:
        raise HTTPException(status_code=403, detail=exc.message)


def _lane_of(work_order: WorkOrder) -> bool:
    return is_auto_repair_lane(
        status=work_order.status,
        vehicle_id=work_order.vehicle_id,
        appointment_id=work_order.appointment_id,
        store_id=work_order.store_id,
    )

def _complete_linked_appointment(db: Session, appointment_id: int) -> None:
    from app.models.appointment import Appointment
    row = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if row and row.status == "CONFIRMED":
        row.status = "COMPLETED"

WORKLOAD_INCREASE_STATUSES = {WorkOrderStatus.ASSIGNED.value}
WORKLOAD_DECREASE_STATUSES = {
    WorkOrderStatus.COMPLETED.value,
    WorkOrderStatus.REJECTED.value,
    WorkOrderStatus.CANCELLED.value,
    WorkOrderStatus.CLOSED.value,
}


def _is_allowed_transition(from_status: str, to_status: str) -> bool:
    return to_status in _allowed_transitions(from_status)


def _attach_transitions(payload, status) -> None:
    """把当前状态和允许的下一步写进列表字典或响应模型。"""
    status_val = _status_value(status)
    targets = _allowed_transitions(status_val)
    if isinstance(payload, dict):
        if status_val is not None:
            payload["status"] = status_val
        payload["allowed_transitions"] = targets
    else:
        payload.allowed_transitions = targets


def _vehicle_plate_map(db: Session, vehicle_ids) -> Dict[int, str]:
    if not vehicle_ids:
        return {}
    from app.models.vehicle import Vehicle
    rows = db.query(Vehicle).filter(Vehicle.id.in_(vehicle_ids)).all()
    return {row.id: row.plate for row in rows}


def _attach_vehicle_plate(resp, db: Session) -> None:
    if not getattr(resp, "vehicle_id", None):
        return
    plates = _vehicle_plate_map(db, {resp.vehicle_id})
    resp.vehicle_plate = plates.get(resp.vehicle_id)


def _add_progress_log(
    db: Session,
    work_order_id: int,
    from_status: Optional[str],
    to_status: str,
    operator_id: Optional[int],
    operator_name: Optional[str],
    source: str,
    remark: Optional[str] = None,
    location: Optional[str] = None,
    attachments: Any = None,
) -> WorkOrderProgressLog:
    log = WorkOrderProgressLog(
        work_order_id=work_order_id,
        from_status=from_status,
        to_status=to_status,
        operator_id=operator_id,
        operator_name=operator_name,
        source=source,
        remark=remark,
        location=location,
        attachments=attachments,
    )
    db.add(log)
    db.flush()
    return log


def _update_workload(db: Session, technician_id: Optional[int], delta: int):
    if not technician_id or delta == 0:
        return
    tech = db.query(User).filter(User.id == technician_id).first()
    if tech:
        new_count = max(0, (tech.current_workload_count or 0) + delta)
        tech.current_workload_count = new_count
        db.flush()


def _do_transition(work_order_id: int, data: WorkOrderTransition, db: Session, current_user: User):
    try:
        to_status_val = data.to_status.upper()
        to_status_enum = WorkOrderStatus(to_status_val)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的目标状态: {data.to_status}")

    work_order = (
        db.query(WorkOrder)
        .filter(WorkOrder.id == work_order_id)
        .first()
    )
    if not work_order:
        raise HTTPException(status_code=404, detail="工单不存在")
    if not row_in_scope(_work_order_scope(current_user, None, None), work_order.store_id):
        raise HTTPException(status_code=404, detail="工单不存在")

    from_status_val = work_order.status.value if work_order.status else None

    if from_status_val == to_status_val:
        return _build_work_order_response(work_order, db)

    if not _is_allowed_transition(from_status_val, to_status_val):
        raise HTTPException(
            status_code=400,
            detail=f"非法状态流转: {from_status_val} → {to_status_val}，允许的目标状态: {VALID_TRANSITIONS.get(from_status_val, [])}"
        )

    is_admin = current_user.role == UserRole.ADMIN.value
    is_supervisor = current_user.role == UserRole.SUPERVISOR.value
    is_technician = current_user.role == UserRole.TECHNICIAN.value
    is_assigned_tech = work_order.technician_id == current_user.id

    if to_status_val == WorkOrderStatus.ACCEPTED.value:
        if not (is_assigned_tech or is_admin):
            raise HTTPException(status_code=403, detail="仅被指派的维修员或管理员可接单")

    elif to_status_val in (WorkOrderStatus.ARRIVED.value, WorkOrderStatus.INSPECTING.value, WorkOrderStatus.IN_PROGRESS.value):
        if not (is_assigned_tech or is_admin):
            raise HTTPException(status_code=403, detail="仅维修员或管理员可推进到此状态")

    elif to_status_val == WorkOrderStatus.ARCHIVING.value:
        # 完成维修 → 待归档：仅被指派维修员或管理员可操作
        if not (is_assigned_tech or is_admin):
            raise HTTPException(status_code=403, detail="仅维修员或管理员可将工单标记为待归档")

    elif to_status_val == WorkOrderStatus.ARCHIVED.value:
        raise HTTPException(status_code=400, detail="归档完成请使用工单归档接口，需 AI 校验完成度达标")

    elif to_status_val == WorkOrderStatus.COMPLETED.value:
        pass

    elif to_status_val == WorkOrderStatus.REJECTED.value:
        if not (is_assigned_tech or is_admin or is_supervisor):
            raise HTTPException(status_code=403, detail="仅维修员、主管或管理员可退回")

    elif to_status_val == WorkOrderStatus.ASSIGNED.value:
        if not (is_supervisor or is_admin):
            raise HTTPException(status_code=403, detail="仅主管或管理员可派工/改派")

    elif to_status_val in (
        WorkOrderStatus.INTAKE.value,
        WorkOrderStatus.DIAGNOSING.value,
        WorkOrderStatus.QUOTING.value,
        WorkOrderStatus.QC.value,
    ):
        is_creator = work_order.created_by == current_user.id
        if not (is_assigned_tech or is_admin or is_supervisor or is_creator):
            raise HTTPException(status_code=403, detail="仅维修员、主管或管理员可推进接车/诊断/报价/质检")

    elif to_status_val == WorkOrderStatus.APPROVED.value:
        if not (is_supervisor or is_admin):
            raise HTTPException(status_code=403, detail="仅主管或管理员可确认报价")

    elif to_status_val == WorkOrderStatus.CLOSED.value:
        if not (is_supervisor or is_admin):
            raise HTTPException(status_code=403, detail="仅主管或管理员可结案")

    elif to_status_val == WorkOrderStatus.CANCELLED.value:
        is_creator = work_order.created_by == current_user.id
        if not (is_assigned_tech or is_admin or is_supervisor or is_creator):
            raise HTTPException(status_code=403, detail="仅维修员、主管或管理员可取消工单")

    old_technician_id = work_order.technician_id
    from_status_enum = work_order.status

    if to_status_val == WorkOrderStatus.CLOSED.value and work_order.appointment_id:
        _complete_linked_appointment(db, work_order.appointment_id)

    if to_status_val == WorkOrderStatus.COMPLETED.value:
        try:
            from app.api.work_orders import complete_work_order_internal as _complete_internal
            complete_result = _complete_internal(work_order_id, db)
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[Transition] 调用complete逻辑失败，继续手动标记完成: {e}")
            work_order.status = to_status_enum
            db.flush()
    else:
        work_order.status = to_status_enum
        db.flush()

    _add_progress_log(
        db=db,
        work_order_id=work_order.id,
        from_status=from_status_enum,
        to_status=to_status_enum,
        operator_id=current_user.id,
        operator_name=current_user.real_name,
        source=data.source or "WEB",
        remark=data.remark,
        location=data.location,
        attachments=data.attachments,
    )

    if from_status_val in WORKLOAD_INCREASE_STATUSES:
        _update_workload(db, old_technician_id, -1)
    if to_status_val in WORKLOAD_INCREASE_STATUSES:
        _update_workload(db, work_order.technician_id, +1)
    if to_status_val in WORKLOAD_DECREASE_STATUSES and from_status_val not in WORKLOAD_DECREASE_STATUSES:
        _update_workload(db, old_technician_id, -1)

    db.commit()
    db.refresh(work_order)

    # 状态变更后，异步刷新维修员钉钉上的派工进度卡片（Web 端操作实时反映到钉钉，不阻塞接口响应）
    # 钉钉卡片回调走 DINGTALK_CARD 来源，卡片已由 dingtalk_wo_card._dispatch_action 异步刷新，此处跳过避免重复。
    if data.source != "DINGTALK_CARD":
        try:
            from app.core.dingtalk_wo_card import _notify_supervisor_async, _refresh_card_async
            from app.models.user import User as _User
            _tech = db.query(_User).filter(_User.id == work_order.technician_id).first()
            if _tech and _tech.dingtalk_userid:
                _refresh_card_async(work_order.id, work_order.work_order_no)
            # 汽修车道复用主管进度通知。没有绑定钉钉时函数内部会跳过。
            if _lane_of(work_order):
                actor = current_user.real_name or current_user.username or ""
                _notify_supervisor_async(
                    work_order.id,
                    STATUS_LABELS.get(to_status_val, to_status_val),
                    actor,
                )
        except Exception as e:
            logger.warning(f"[Transition] 钉钉进度卡片刷新失败（不影响工单状态）: {e}")

    if work_order.customer_id or work_order.vehicle_id:
        try:
            from app.domain.owner_notify import notify_owner
            from app.models.vehicle import Vehicle
            plate = ""
            if work_order.vehicle_id:
                vehicle = db.query(Vehicle).filter(Vehicle.id == work_order.vehicle_id).first()
                plate = vehicle.plate if vehicle else ""
            notify_owner(
                db,
                customer_id=work_order.customer_id,
                vehicle_id=work_order.vehicle_id,
                work_order_id=work_order.id,
                work_order_no=work_order.work_order_no,
                status_label=STATUS_LABELS.get(to_status_val, to_status_val),
                plate=plate,
            )
        except Exception as e:
            logger.warning(f"[Transition] 车主通知失败（不影响工单状态）: {e}")

    if to_status_val == WorkOrderStatus.CLOSED.value:
        try:
            from app.domain.follow_up import schedule_after_delivery
            schedule_after_delivery(db, work_order, created_by=current_user.id)
            db.commit()
        except Exception as e:
            logger.warning(f"[Transition] 回访提醒排期失败（不影响工单状态）: {e}")
            try:
                db.rollback()
            except Exception:
                pass

    logger.info(f"[WorkOrder] 状态流转 #{work_order.id}: {from_status_val} → {to_status_val} by {current_user.real_name}")
    return _build_work_order_response(work_order, db)

def _build_work_order_response(work_order: WorkOrder, db: Session) -> WorkOrderResponse:
    resp = WorkOrderResponse.model_validate(work_order)
    if work_order.created_by:
        creator = db.query(User).filter(User.id == work_order.created_by).first()
        resp.created_by_employee_id = creator.employee_id if creator else None
    if work_order.technician_id:
        tech = db.query(User).filter(User.id == work_order.technician_id).first()
        resp.technician_name = tech.real_name if tech else None
    _attach_transitions(resp, work_order.status)
    _attach_vehicle_plate(resp, db)
    if work_order.progress_logs:
        resp.progress_logs = [
            WorkOrderProgressLogResponse(
                id=l.id,
                work_order_id=l.work_order_id,
                from_status=l.from_status.value if l.from_status else None,
                to_status=l.to_status.value if l.to_status else None,
                operator_id=l.operator_id,
                operator_name=l.operator_name,
                source=l.source,
                remark=l.remark,
                location=l.location,
                attachments=l.attachments,
                created_at=l.created_at,
            )
            for l in work_order.progress_logs
        ]
    return resp


# 对外稳定名（API / 通道层使用）；下划线名保留给本模块内部互调。
parse_store_header = _parse_store_header
work_order_scope = _work_order_scope
lane_of = _lane_of
complete_linked_appointment = _complete_linked_appointment
is_allowed_transition = _is_allowed_transition
attach_transitions = _attach_transitions
vehicle_plate_map = _vehicle_plate_map
attach_vehicle_plate = _attach_vehicle_plate
add_progress_log = _add_progress_log
update_workload = _update_workload
build_work_order_response = _build_work_order_response
do_transition = _do_transition
