from sqlalchemy import Column, String, Integer, Float, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from app.models.base import BaseModel


class SparePart(BaseModel):
    __tablename__ = "spare_parts"

    part_code = Column(String(50), unique=True, nullable=False, index=True)
    part_name = Column(String(200), nullable=False)
    specification = Column(String(200))
    unit = Column(String(20), default="个")
    stock_quantity = Column(Integer, default=0)
    safety_stock = Column(Integer, default=0)
    unit_price = Column(Float, default=0.0)
    device_type = Column(String(100))
    location = Column(String(200))
    supplier = Column(String(200))
    sku_id = Column(Integer, ForeignKey("part_skus.id", ondelete="SET NULL"), nullable=True, index=True, comment="关联配件目录 SKU")
    fitment = Column(JSONB, comment="适配规则 [{brand, series, year_from, year_to, engine}]，空字段表示该维不限")

    def __repr__(self):
        return f"<SparePart(part_code='{self.part_code}', part_name='{self.part_name}')>"