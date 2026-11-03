from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class Quote(BaseModel):
    """报价单。草案可由工单领料或问诊建议生成，店员确认后车主再确认。"""

    __tablename__ = "quotes"

    quote_no = Column(String(50), unique=True, nullable=False, index=True, comment="报价单号")
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(30), nullable=False, default="DRAFT", index=True, comment="DRAFT/STAFF_CONFIRMED/CUSTOMER_CONFIRMED/REJECTED/CANCELLED")
    customer_confirm = Column(Boolean, nullable=False, default=False, comment="车主是否已确认")
    total = Column(Float, nullable=False, default=0.0, comment="合计")
    mileage = Column(Integer, comment="生成报价时的里程 km")
    symptoms = Column(Text, comment="症状原文")
    consult_text = Column(Text, comment="问诊建议原文")
    note = Column(Text, comment="生成说明")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    staff_confirmed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    customer_confirmed_at = Column(DateTime, nullable=True)

    lines = relationship(
        "QuoteLine",
        back_populates="quote",
        cascade="all, delete-orphan",
        order_by="QuoteLine.line_no",
    )

    def __repr__(self):
        return f"<Quote(quote_no='{self.quote_no}', status='{self.status}')>"


class QuoteLine(BaseModel):
    __tablename__ = "quote_lines"

    quote_id = Column(Integer, ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no = Column(Integer, nullable=False, default=1)
    line_type = Column(String(20), nullable=False, default="LABOR", comment="PART/LABOR/PACKAGE")
    name = Column(String(200), nullable=False)
    code = Column(String(50))
    qty = Column(Float, nullable=False, default=1)
    unit_price = Column(Float, nullable=False, default=0)
    amount = Column(Float, nullable=False, default=0)
    source = Column(String(30), comment="work_order/consult/package/manual")
    ref_id = Column(Integer, comment="来源配件、项目或套餐 id")

    quote = relationship("Quote", back_populates="lines")

    def __repr__(self):
        return f"<QuoteLine(name='{self.name}', amount={self.amount})>"
