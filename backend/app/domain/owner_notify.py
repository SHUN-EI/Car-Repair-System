"""车主进度通知。只走已经接好的阿里云短信和钉钉工作通知，不新增渠道。

短信未打开时在日志和标准输出留一条，便于对测试号核对文案。
钉钉默认 Mock，打开真实发送见 docs/phase2-启用说明.md。
"""
from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dingtalk import dingtalk
from app.core.sms import sms_service
from app.models.customer import Customer
from app.models.notification import Notification
from app.models.user import User
from app.models.vehicle import Vehicle


def owner_status_text(work_order_no: str, status_label: str, plate: str = "") -> str:
    plate_text = f"，车牌{plate}" if plate else ""
    return f"工单{work_order_no}{plate_text}，当前进度：{status_label}。"


def _customer_for(db: Session, customer_id: Optional[int], vehicle_id: Optional[int]) -> Optional[Customer]:
    if customer_id:
        row = db.query(Customer).filter(Customer.id == customer_id).first()
        if row:
            return row
    if vehicle_id:
        vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
        if vehicle and vehicle.owner_id:
            return db.query(Customer).filter(Customer.id == vehicle.owner_id).first()
    return None


def notify_owner(
    db: Session,
    *,
    customer_id: Optional[int] = None,
    vehicle_id: Optional[int] = None,
    work_order_id: Optional[int] = None,
    work_order_no: str = "",
    status_label: str = "",
    plate: str = "",
    title: str = "",
) -> dict:
    """失败只记在返回值里，不抛给工单流转。"""
    result = {"sms": "skipped", "dingtalk": "skipped", "inbox": "skipped"}
    try:
        customer = _customer_for(db, customer_id, vehicle_id)
        if customer is None:
            result["reason"] = "无客户"
            return result
        content = owner_status_text(work_order_no or "-", status_label or "状态更新", plate)
        notice_title = title or f"工单进度 {work_order_no or ''}".strip()
        if customer.phone:
            result["sms"] = sms_service.send_notice(customer.phone, {
                "work_order_no": work_order_no or "-",
                "status": status_label or "状态更新",
            })
        user = None
        if customer.user_id:
            user = db.query(User).filter(User.id == customer.user_id).first()
        if user is not None:
            db.add(Notification(
                user_id=user.id,
                type="work_order",
                title=notice_title[:200],
                content=content,
                work_order_id=work_order_id,
            ))
            db.commit()
            result["inbox"] = "sent"
            if user.dingtalk_userid:
                ok = dingtalk.send_work_notice(user.dingtalk_userid, notice_title, content)
                if settings.DINGTALK_MOCK_MODE:
                    result["dingtalk"] = "mock" if ok else "failed"
                else:
                    result["dingtalk"] = "sent" if ok else "failed"
        logger.info(
            f"[OwnerNotify] {work_order_no} {status_label} "
            f"sms={result['sms']} dingtalk={result['dingtalk']} inbox={result['inbox']}"
        )
        return result
    except Exception as exc:
        logger.warning(f"[OwnerNotify] 发送失败（不影响业务单据）: {exc}")
        try:
            db.rollback()
        except Exception:
            pass
        result["error"] = "通知发送失败"
        return result
