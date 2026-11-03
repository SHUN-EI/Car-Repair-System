from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import BaseModel


class ServicePackage(BaseModel):
    """保养套餐。品牌、车系、里程留空表示这一维不限制。"""

    __tablename__ = "service_packages"

    code = Column(String(50), unique=True, nullable=False, index=True, comment="套餐编码")
    name = Column(String(200), nullable=False, comment="套餐名称")
    description = Column(Text, comment="说明")
    brand = Column(String(50), comment="适用品牌，空为不限")
    series = Column(String(80), comment="适用车系，空为不限")
    mileage_from = Column(Integer, comment="里程下限 km，空为不限")
    mileage_to = Column(Integer, comment="里程上限 km，空为不限")
    symptom_keywords = Column(JSONB, comment="症状关键词")
    list_price = Column(Float, nullable=False, default=0.0, comment="套餐价")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否在售")

    def __repr__(self):
        return f"<ServicePackage(code='{self.code}', name='{self.name}')>"


class ServiceSku(BaseModel):
    """服务项目。可以挂在套餐下，也可以单独售卖。"""

    __tablename__ = "service_skus"

    code = Column(String(50), unique=True, nullable=False, index=True, comment="项目编码")
    name = Column(String(200), nullable=False, comment="项目名称")
    labor_minutes = Column(Integer, nullable=False, default=0, comment="工时分钟")
    base_price = Column(Float, nullable=False, default=0.0, comment="基础价")
    package_id = Column(
        Integer,
        ForeignKey("service_packages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="所属套餐",
    )
    category = Column(String(50), comment="类别：保养/维修/检测")
    symptom_keywords = Column(JSONB, comment="症状关键词")
    brand = Column(String(50), comment="适用品牌，空为不限")
    series = Column(String(80), comment="适用车系，空为不限")
    mileage_from = Column(Integer, comment="里程下限 km")
    mileage_to = Column(Integer, comment="里程上限 km")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否在售")

    def __repr__(self):
        return f"<ServiceSku(code='{self.code}', name='{self.name}')>"
