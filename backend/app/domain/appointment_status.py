"""预约单的轻量状态。字符串字段，不建 Postgres 枚举，方便后续加状态。"""
from typing import Dict, List

APPOINTMENT_STATUSES = ("PENDING", "CONFIRMED", "CANCELLED", "COMPLETED")

APPOINTMENT_LABELS = {
    "PENDING": "待确认",
    "CONFIRMED": "已确认",
    "CANCELLED": "已取消",
    "COMPLETED": "已完成",
}

APPOINTMENT_TRANSITIONS: Dict[str, List[str]] = {
    "PENDING": ["CONFIRMED", "CANCELLED"],
    "CONFIRMED": ["CANCELLED", "COMPLETED"],
    "CANCELLED": [],
    "COMPLETED": [],
}


def appointment_targets(status: str) -> List[str]:
    return list(APPOINTMENT_TRANSITIONS.get(status or "", []))


def is_allowed_appointment_transition(from_status: str, to_status: str) -> bool:
    if from_status == to_status:
        return True
    return to_status in appointment_targets(from_status)
