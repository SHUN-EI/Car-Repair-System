from sqlalchemy import Column, String, Text, Integer, ForeignKey
from app.models.base import BaseModel


class Customer(BaseModel):
    """客户（车主档案骨架）。车辆通过 owner_id 指向这里。"""

    __tablename__ = "customers"

    name = Column(String(100), nullable=False, comment="客户姓名")
    phone = Column(String(20), index=True, comment="手机号")
    email = Column(String(200), comment="邮箱")
    id_no = Column(String(30), comment="证件号占位，Phase 0 不校验格式")
    remark = Column(Text, comment="备注")
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="可选关联系统用户（客户本人有账号时）",
    )

    def __repr__(self):
        return f"<Customer(name='{self.name}', phone='{self.phone}')>"
