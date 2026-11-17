"""配件库存主数据：编码、名称、总库存、安全库存、单价和可选的车型适配规则。门店结存在 store_part_stocks。"""

from sqlalchemy import Column, String, Integer, Float, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from app.models.base import BaseModel


class SparePart(BaseModel):
    """配件库存记录。stock_quantity 是仓库总库存；fitment 存放适配规则 JSON；store_id 用于历史分店数据，现网门店结存以后者分表为准。"""
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
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True, comment="归属门店，空表示未分店")
    fitment = Column(JSONB, comment="适配规则 [{brand, series, year_from, year_to, engine}]，空字段表示该维不限")

    def __repr__(self):
        """调试时输出配件主键、编码和名称。"""
        return f"<SparePart(part_code='{self.part_code}', part_name='{self.part_name}')>"