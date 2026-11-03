from sqlalchemy import Column, Float, ForeignKey, Integer, String

from app.models.base import BaseModel


class PaymentIntent(BaseModel):
    """支付意向占位。只记录要收的金额，不调用支付渠道，也没有成功态。"""

    __tablename__ = "payment_intents"

    intent_no = Column(String(40), unique=True, nullable=False, index=True, comment="意向单号")
    quote_id = Column(Integer, ForeignKey("quotes.id", ondelete="SET NULL"), nullable=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    amount = Column(Float, nullable=False, default=0, comment="金额，来自报价合计")
    currency = Column(String(8), nullable=False, default="CNY")
    channel = Column(String(20), nullable=False, default="STUB", comment="固定 STUB，未接渠道")
    status = Column(String(20), nullable=False, default="CREATED", index=True, comment="CREATED/CANCELLED")
    note = Column(String(200), nullable=False, default="占位订单，未接入清算")

    def __repr__(self):
        return f"<PaymentIntent(intent_no='{self.intent_no}', status='{self.status}')>"
