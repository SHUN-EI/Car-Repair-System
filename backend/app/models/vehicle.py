from sqlalchemy import Column, String, Integer, ForeignKey
from app.models.base import BaseModel


class Vehicle(BaseModel):
    """车辆档案。车主指向客户，不直接绑系统用户。"""

    __tablename__ = "vehicles"

    plate = Column(String(20), unique=True, nullable=False, index=True, comment="车牌号")
    vin = Column(String(17), unique=True, nullable=True, index=True, comment="车架号 VIN，可空")
    make = Column(String(50), comment="品牌")
    model = Column(String(80), comment="车型")
    year = Column(Integer, comment="年款")
    owner_id = Column(
        Integer,
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="车主，关联客户",
    )

    def __repr__(self):
        return f"<Vehicle(plate='{self.plate}', vin='{self.vin}')>"
