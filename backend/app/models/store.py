from sqlalchemy import Column, String, Boolean, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.models.base import BaseModel


class Store(BaseModel):
    """门店骨架。"""

    __tablename__ = "stores"

    code = Column(String(50), unique=True, nullable=False, index=True, comment="门店编码")
    name = Column(String(200), nullable=False, comment="门店名称")
    address = Column(String(300), comment="地址")
    phone = Column(String(20), comment="联系电话")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否营业")

    bays = relationship("Bay", back_populates="store")

    def __repr__(self):
        return f"<Store(code='{self.code}', name='{self.name}')>"


class Bay(BaseModel):
    """工位骨架，归属门店。"""

    __tablename__ = "bays"
    __table_args__ = (
        UniqueConstraint("store_id", "code", name="uq_bays_store_code"),
    )

    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属门店")
    code = Column(String(50), nullable=False, comment="工位编码，门店内唯一")
    name = Column(String(100), nullable=False, comment="工位名称")
    bay_type = Column(String(30), default="通用", comment="工位类型：通用/机电/钣喷")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否可用")

    store = relationship("Store", back_populates="bays")

    def __repr__(self):
        return f"<Bay(code='{self.code}', store_id={self.store_id})>"
