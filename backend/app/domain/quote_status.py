"""报价单状态。店员先确认草案，车主再确认。没有支付成功态。"""
from typing import Dict, List


QUOTE_STATUSES = (
    "DRAFT",
    "STAFF_CONFIRMED",
    "CUSTOMER_CONFIRMED",
    "REJECTED",
    "CANCELLED",
)

QUOTE_LABELS: Dict[str, str] = {
    "DRAFT": "草案",
    "STAFF_CONFIRMED": "店员已确认",
    "CUSTOMER_CONFIRMED": "车主已确认",
    "REJECTED": "已拒绝",
    "CANCELLED": "已取消",
}

QUOTE_TRANSITIONS: Dict[str, List[str]] = {
    "DRAFT": ["STAFF_CONFIRMED", "CANCELLED"],
    "STAFF_CONFIRMED": ["CUSTOMER_CONFIRMED", "REJECTED", "CANCELLED"],
    "CUSTOMER_CONFIRMED": [],
    "REJECTED": [],
    "CANCELLED": [],
}


def can_transition(src: str, dest: str) -> bool:
    return dest in QUOTE_TRANSITIONS.get(src or "", [])
