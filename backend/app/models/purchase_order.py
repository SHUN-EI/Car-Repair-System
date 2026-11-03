from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class PurchaseOrder(BaseModel):
    """备件采购单。入库后才增加库存。"""

    __tablename__ = "purchase_orders"

    po_no = Column(String(40), unique=True, nullable=False, index=True, comment="采购单号")
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, index=True)
    supplier = Column(String(200), nullable=True, comment="供应商")
    status = Column(String(20), nullable=False, default="ORDERED", index=True, comment="ORDERED/PARTIAL/RECEIVED/CANCELLED")
    note = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    lines = relationship(
        "PurchaseOrderLine",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLine.id",
    )

    def __repr__(self):
        return f"<PurchaseOrder(po_no='{self.po_no}', status='{self.status}')>"


class PurchaseOrderLine(BaseModel):
    __tablename__ = "purchase_order_lines"

    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    spare_part_id = Column(Integer, ForeignKey("spare_parts.id", ondelete="SET NULL"), nullable=True)
    part_code = Column(String(50), nullable=False, comment="备件编码")
    part_name = Column(String(200), nullable=False, comment="备件名称")
    qty_ordered = Column(Integer, nullable=False)
    qty_received = Column(Integer, nullable=False, default=0)
    unit_price = Column(Float, nullable=False, default=0)

    order = relationship("PurchaseOrder", back_populates="lines")

    def __repr__(self):
        return f"<PurchaseOrderLine(part_code='{self.part_code}', qty_ordered={self.qty_ordered})>"
