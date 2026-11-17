"""车主账号和客户档案的对应关系。

车辆的 owner_id 指向客户，客户的 user_id 指向登录用户。
车主 H5 只看自己的客户、车辆、预约和工单。
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.user import User


def customers_for_user(db: Session, user: User) -> List[Customer]:
    """查出当前账号绑定的全部客户档案，按主键升序返回。用户为空时返回空列表。"""
    if user is None:
        return []
    return db.query(Customer).filter(Customer.user_id == user.id).order_by(Customer.id.asc()).all()


def customer_ids_for_user(db: Session, user: User) -> List[int]:
    """返回当前账号绑定的客户档案 ID 列表，供车主数据过滤使用。"""
    return [row.id for row in customers_for_user(db, user)]


def ensure_customer_for_user(db: Session, user: User) -> Customer:
    """保证当前账号至少有一条客户档案：已有则返回最早的一条，没有则用姓名/手机/邮箱自动建档并 flush，备注为「车主账号自动建档」。"""
    rows = customers_for_user(db, user)
    if rows:
        return rows[0]
    row = Customer(
        name=(user.real_name or user.username or "车主").strip(),
        phone=user.phone,
        email=user.email,
        user_id=user.id,
        remark="车主账号自动建档",
    )
    db.add(row)
    db.flush()
    return row


def is_owner(user: Optional[User]) -> bool:
    """判断用户角色是否为车主 OWNER。用户为空返回 False；兼容枚举或字符串两种 role 存法。"""
    if user is None:
        return False
    role = user.role.value if hasattr(user.role, "value") else user.role
    return role == "OWNER"
