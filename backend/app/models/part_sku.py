from sqlalchemy import Column, String, Float, Boolean
from app.models.base import BaseModel


class PartSku(BaseModel):
    """配件目录（SKU 主数据）。库存数量仍在 spare_parts，这里只放目录字段和价格占位。"""

    __tablename__ = "part_skus"

    code = Column(String(50), unique=True, nullable=False, index=True, comment="SKU 编码")
    name = Column(String(200), nullable=False, comment="配件名称")
    brand = Column(String(100), comment="品牌")
    unit = Column(String(20), default="个", comment="单位")
    list_price = Column(Float, default=0.0, comment="指导价占位")
    cost_price = Column(Float, default=0.0, comment="成本价占位")
    specification = Column(String(200), comment="规格")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否在售")

    def __repr__(self):
        return f"<PartSku(code='{self.code}', name='{self.name}')>"
