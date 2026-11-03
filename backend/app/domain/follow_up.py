"""交车后的回访 / 评价提醒。

只负责排期和到期发送。文案走现有车主通知（短信、钉钉、站内），
不统计回复率，也不编造成功率。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.domain.owner_notify import notify_owner

FOLLOW_UP_KINDS = ("REVISIT", "RATING")
FOLLOW_UP_STATUSES = ("SCHEDULED", "SENT", "CANCELLED", "SKIPPED")
KIND_LABELS = {"REVISIT": "回访复查", "RATING": "服务评价"}
# 交车后默认间隔。这是排期配置，不是经营指标。
DEFAULT_DELAY_DAYS = {"RATING": 1, "REVISIT": 7}
DELIVERED_CHANNELS = {"sent", "mock"}


def follow_up_message(kind: str, work_order_no: str, plate: str = "") -> str:
    plate_text = f"，车牌{plate}" if plate else ""
    no = work_order_no or "-"
    if kind == "REVISIT":
        return f"工单{no}{plate_text}已交车，可预约回访复查。"
    return f"工单{no}{plate_text}已交车，欢迎对本次服务进行评价。"


def status_label_for(kind: str) -> str:
    return "邀请回访" if kind == "REVISIT" else "邀请评价"


def reminder_delivered(result: Optional[dict]) -> bool:
    if not result:
        return False
    return any(result.get(key) in DELIVERED_CHANNELS for key in ("sms", "dingtalk", "inbox"))


def schedule_reminder(
    db: Session,
    *,
    work_order_id: int,
    kind: str,
    scheduled_at: datetime,
    store_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    vehicle_id: Optional[int] = None,
    note: Optional[str] = None,
    created_by: Optional[int] = None,
):
    """同一工单同一种提醒，未发送的只保留一条。"""
    from app.models.follow_up import FollowUpReminder

    kind = (kind or "").strip().upper()
    if kind not in FOLLOW_UP_KINDS:
        raise ValueError("提醒类型只能是回访或评价")
    existing = (
        db.query(FollowUpReminder)
        .filter(
            FollowUpReminder.work_order_id == work_order_id,
            FollowUpReminder.kind == kind,
            FollowUpReminder.status == "SCHEDULED",
        )
        .first()
    )
    if existing:
        return existing
    row = FollowUpReminder(
        store_id=store_id,
        work_order_id=work_order_id,
        customer_id=customer_id,
        vehicle_id=vehicle_id,
        kind=kind,
        status="SCHEDULED",
        scheduled_at=scheduled_at,
        note=note,
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row


def schedule_after_delivery(db: Session, work_order, *, created_by: Optional[int] = None, now: Optional[datetime] = None) -> list:
    """结案交车时排一条评价、一条回访。已有未发送记录则跳过。"""
    now = now or datetime.utcnow()
    created = []
    for kind in ("RATING", "REVISIT"):
        when = now + timedelta(days=DEFAULT_DELAY_DAYS[kind])
        before = _scheduled_id(db, work_order.id, kind)
        row = schedule_reminder(
            db,
            work_order_id=work_order.id,
            kind=kind,
            scheduled_at=when,
            store_id=getattr(work_order, "store_id", None),
            customer_id=getattr(work_order, "customer_id", None),
            vehicle_id=getattr(work_order, "vehicle_id", None),
            note="交车后自动排期",
            created_by=created_by,
        )
        if before is None or before != row.id:
            created.append(row)
    return created


def _scheduled_id(db: Session, work_order_id: int, kind: str):
    from app.models.follow_up import FollowUpReminder

    row = (
        db.query(FollowUpReminder.id)
        .filter(
            FollowUpReminder.work_order_id == work_order_id,
            FollowUpReminder.kind == kind,
            FollowUpReminder.status == "SCHEDULED",
        )
        .first()
    )
    return row[0] if row else None


def dispatch_due(db: Session, *, now: Optional[datetime] = None, limit: int = 100) -> dict:
    """发送已到期且仍为待发送的提醒。没有客户时记为跳过，不假装已送达。"""
    from app.models.follow_up import FollowUpReminder
    from app.models.vehicle import Vehicle
    from app.models.work_order import WorkOrder

    now = now or datetime.utcnow()
    rows = (
        db.query(FollowUpReminder)
        .filter(
            FollowUpReminder.status == "SCHEDULED",
            FollowUpReminder.scheduled_at <= now,
        )
        .order_by(FollowUpReminder.scheduled_at.asc(), FollowUpReminder.id.asc())
        .limit(limit)
        .all()
    )
    sent = 0
    skipped = 0
    for row in rows:
        work_order = db.query(WorkOrder).filter(WorkOrder.id == row.work_order_id).first()
        work_order_no = work_order.work_order_no if work_order else ""
        plate = ""
        vehicle_id = row.vehicle_id or (work_order.vehicle_id if work_order else None)
        if vehicle_id:
            vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
            plate = vehicle.plate if vehicle else ""
        content = follow_up_message(row.kind, work_order_no, plate)
        result = notify_owner(
            db,
            customer_id=row.customer_id or (work_order.customer_id if work_order else None),
            vehicle_id=vehicle_id,
            work_order_id=row.work_order_id,
            work_order_no=work_order_no,
            status_label=status_label_for(row.kind),
            plate=plate,
            title=f"{KIND_LABELS.get(row.kind, '提醒')} {work_order_no}".strip(),
            content=content,
            notice_type="follow_up",
        )
        row.channel_result = result
        row.sent_at = now
        if reminder_delivered(result):
            row.status = "SENT"
            sent += 1
        else:
            row.status = "SKIPPED"
            skipped += 1
        db.commit()
    return {"checked": sent + skipped, "sent": sent, "skipped": skipped}


def run_follow_up_dispatch() -> dict:
    """给定时任务调用。失败只记日志，不抛出。"""
    from loguru import logger
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        result = dispatch_due(db)
        logger.info(f"[FollowUp] 到期提醒 checked={result['checked']} sent={result['sent']} skipped={result['skipped']}")
        return result
    except Exception as exc:
        logger.warning(f"[FollowUp] 到期提醒失败: {exc}")
        try:
            db.rollback()
        except Exception:
            pass
        return {"checked": 0, "sent": 0, "skipped": 0, "error": "发送失败"}
    finally:
        db.close()
