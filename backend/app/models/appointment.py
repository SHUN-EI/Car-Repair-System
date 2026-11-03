from sqlalchemy import Column, String, Text, Integer, ForeignKey, DateTime
from app.models.base import BaseModel


class Appointment(BaseModel):
    """预约骨架。状态用字符串，转移见 app.domain.appointment_status。"""

    __tablename__ = "appointments"

    store_id = Column(Integer, ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, index=True, comment="预约门店")
    bay_id = Column(Integer, ForeignKey("bays.id", ondelete="SET NULL"), nullable=True, comment="预约工位，可空")
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True, comment="客户")
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True, comment="车辆")
    scheduled_at = Column(DateTime, nullable=False, comment="预约到店时间")
    status = Column(String(20), nullable=False, default="PENDING", comment="PENDING/CONFIRMED/CANCELLED/COMPLETED")
    remark = Column(Text, comment="备注")

    def __repr__(self):
        return f"<Appointment(id={self.id}, status='{self.status}')>"
