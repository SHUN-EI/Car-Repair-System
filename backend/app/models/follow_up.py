from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import BaseModel


class FollowUpReminder(BaseModel):
    """交车后的回访或评价提醒。到期后由任务发送，不在这里记评分。"""

    __tablename__ = "follow_up_reminders"

    store_id = Column(Integer, ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(20), nullable=False, comment="REVISIT 回访 / RATING 评价")
    status = Column(String(20), nullable=False, default="SCHEDULED", index=True, comment="SCHEDULED/SENT/CANCELLED/SKIPPED")
    scheduled_at = Column(DateTime, nullable=False, index=True, comment="计划发送时间")
    sent_at = Column(DateTime, nullable=True)
    channel_result = Column(JSONB, nullable=True, comment="短信/钉钉/站内的发送结果")
    note = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    def __repr__(self):
        return f"<FollowUpReminder(work_order_id={self.work_order_id}, kind='{self.kind}', status='{self.status}')>"
