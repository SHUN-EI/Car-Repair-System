"""排班与出勤占位：按日期、班次记录谁当班，也可由已批准的请假明细生成请假班次。"""

from sqlalchemy import Column, Integer, String, Date, TIMESTAMP, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
import enum


class ShiftType(str, enum.Enum):
    """班次枚举：早班 MORNING、午班 AFTERNOON、夜班 NIGHT。"""
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"
    NIGHT = "NIGHT"


class DutySchedule(BaseModel):
    """一条排班记录。schedule_type 区分正常出勤和请假等来源；若由请假生成，会记下关联的请假单和替班对象。"""
    __tablename__ = "duty_schedules"

    date = Column(Date, nullable=False, index=True)
    shift = Column(String(20), nullable=False, server_default=ShiftType.MORNING.value)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_type = Column(String(30), nullable=False, server_default="MANUAL",
                           comment="WEEKLY_ROUTINE / MANUAL / LEAVE / SUBSTITUTE")
    note = Column(String(200), nullable=True)
    leave_type = Column(String(30), nullable=True)
    leave_status = Column(String(20), nullable=False, server_default='APPROVED')
    source_leave_request_id = Column(Integer, ForeignKey("leave_requests.id", ondelete="SET NULL"), nullable=True,
                                     comment="生成这条排班记录的请假申请 ID；便于追溯/撤销")
    source_substitute_for_id = Column(Integer, nullable=True,
                                   comment="若 schedule_type=SUBSTITUTE 时，顶替的是哪个请假申请 id（冗余）")
    created_at = Column(TIMESTAMP, nullable=False, server_default="now()")

    user = relationship("User", back_populates="duty_schedules")
    source_leave_request = relationship("LeaveRequest", foreign_keys=[source_leave_request_id])

    __table_args__ = (
        Index("ix_duty_date_shift", "date", "shift"),
    )
