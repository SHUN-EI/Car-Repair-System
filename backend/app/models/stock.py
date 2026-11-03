from sqlalchemy import Column, ForeignKey, Integer, String, Text, UniqueConstraint

from app.models.base import BaseModel


class StorePartStock(BaseModel):
    """门店结存。备件表上的 stock_quantity 仍是仓库总库存。"""

    __tablename__ = "store_part_stocks"
    __table_args__ = (
        UniqueConstraint("store_id", "spare_part_id", name="uq_store_part_stock"),
    )

    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    spare_part_id = Column(Integer, ForeignKey("spare_parts.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=0, comment="本店结存")

    def __repr__(self):
        return f"<StorePartStock(store_id={self.store_id}, spare_part_id={self.spare_part_id}, quantity={self.quantity})>"


class StockMovement(BaseModel):
    """库存流水。采购入库、导入和领料各记一条。"""

    __tablename__ = "stock_movements"

    store_id = Column(Integer, ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True)
    spare_part_id = Column(Integer, ForeignKey("spare_parts.id", ondelete="SET NULL"), nullable=True, index=True)
    part_code = Column(String(50), nullable=False)
    qty_delta = Column(Integer, nullable=False, comment="正数入库，负数出库")
    movement_type = Column(String(30), nullable=False, comment="PO_RECEIVE/IMPORT/ISSUE")
    ref_type = Column(String(30), nullable=True, comment="purchase_order/work_order/import")
    ref_id = Column(Integer, nullable=True)
    balance_after = Column(Integer, nullable=True, comment="变动后的总库存")
    store_balance_after = Column(Integer, nullable=True, comment="变动后的本店结存")
    operator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note = Column(Text, nullable=True)

    def __repr__(self):
        return f"<StockMovement(part_code='{self.part_code}', qty_delta={self.qty_delta})>"
