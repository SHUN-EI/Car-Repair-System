"""车主账号和客户档案的对应关系。

车辆的 owner_id 指向客户，客户的 user_id 指向登录用户。
车主 H5 只看自己的客户、车辆、预约和工单。
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.user import User


def customers_for_user(db: Session, user: User) -> List[Customer]:
    if user is None:
        return []
    return db.query(Customer).filter(Customer.user_id == user.id).order_by(Customer.id.asc()).all()


def customer_ids_for_user(db: Session, user: User) -> List[int]:
    return [row.id for row in customers_for_user(db, user)]


def ensure_customer_for_user(db: Session, user: User) -> Customer:
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
    if user is None:
        return False
    role = user.role.value if hasattr(user.role, "value") else user.role
    return role == "OWNER"
