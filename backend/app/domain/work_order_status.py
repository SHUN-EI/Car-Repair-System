"""工单状态机。

现网已经有一条工业维修车道（草稿 → 派工 → 接单 → 到场 → 检查 → 维修 → 待归档 → 归档），
钉钉卡片、主管派工和知识归档都依赖这些状态和转移，不能删边。

Phase 0 在同一张状态表上追加汽修车道，只增加允许的转移：

    DRAFT → INTAKE → DIAGNOSING → QUOTING → APPROVED → IN_PROGRESS → QC → COMPLETED → CLOSED

非终态可以转到 CANCELLED。APPROVED 原先是没有入边的兼容终态，这里重新作为「报价已确认」使用；
现网派工不会进入 APPROVED。COMPLETED 增加出边 CLOSED，钉钉「完成」仍停在 COMPLETED，不会自动结案。
IN_PROGRESS 仍可去 ARCHIVING / REJECTED，并多一条 QC。

维修报表的 PUT 保存会把已填写的草稿直接标成 IN_PROGRESS，那是既有捷径，不经过本表。
"""
from typing import Dict, List, Optional


# 键是状态值，值是允许的目标状态。工业车道的原有边必须保留。
VALID_TRANSITIONS: Dict[str, List[str]] = {
    "DRAFT": ["SUBMITTED", "ASSIGNED", "INTAKE", "CANCELLED"],
    "SUBMITTED": ["ASSIGNED", "REJECTED", "CANCELLED"],
    "ASSIGNED": ["ACCEPTED", "REJECTED", "CANCELLED"],
    "ACCEPTED": ["ARRIVED", "REJECTED", "CANCELLED"],
    "ARRIVED": ["INSPECTING", "REJECTED", "CANCELLED"],
    "INSPECTING": ["IN_PROGRESS", "REJECTED", "CANCELLED"],
    "IN_PROGRESS": ["ARCHIVING", "REJECTED", "QC", "CANCELLED"],
    "ARCHIVING": ["ARCHIVED", "CANCELLED"],
    "COMPLETED": ["CLOSED"],
    "REJECTED": [],
    "STANDARDIZED": [],
    "CLASSIFIED": [],
    "APPROVED": ["IN_PROGRESS", "CANCELLED"],
    "ARCHIVED": [],
    "INTAKE": ["DIAGNOSING", "CANCELLED"],
    "DIAGNOSING": ["QUOTING", "CANCELLED"],
    "QUOTING": ["APPROVED", "CANCELLED"],
    "QC": ["COMPLETED", "CANCELLED"],
    "CLOSED": [],
    "CANCELLED": [],
}

# 汽修主路径（不含取消）。APPROVED / IN_PROGRESS / COMPLETED / DRAFT 与工业枚举复用。
AUTO_REPAIR_PATH: List[str] = [
    "DRAFT",
    "INTAKE",
    "DIAGNOSING",
    "QUOTING",
    "APPROVED",
    "IN_PROGRESS",
    "QC",
    "COMPLETED",
    "CLOSED",
]

STATUS_LABELS: Dict[str, str] = {
    "DRAFT": "草稿",
    "SUBMITTED": "待派工",
    "ASSIGNED": "已派单",
    "ACCEPTED": "已接单",
    "ARRIVED": "已到达",
    "INSPECTING": "检查中",
    "IN_PROGRESS": "维修中",
    "ARCHIVING": "待归档",
    "ARCHIVED": "已归档",
    "COMPLETED": "已完成",
    "REJECTED": "已退回",
    "STANDARDIZED": "已标准化",
    "CLASSIFIED": "已分类",
    "APPROVED": "报价已确认",
    "INTAKE": "接车",
    "DIAGNOSING": "诊断中",
    "QUOTING": "报价中",
    "QC": "质检",
    "CLOSED": "已结案",
    "CANCELLED": "已取消",
}


def status_value(status) -> Optional[str]:
    if status is None:
        return None
    return status.value if hasattr(status, "value") else str(status)


def allowed_transitions(status) -> List[str]:
    key = status_value(status)
    if not key:
        return []
    return list(VALID_TRANSITIONS.get(key, []))


def is_allowed_transition(from_status, to_status: str) -> bool:
    return to_status in allowed_transitions(from_status)


def status_machine_payload() -> dict:
    """给 API 用的状态目录：每个状态、中文名、以及允许的下一步。"""
    statuses = []
    for value, targets in VALID_TRANSITIONS.items():
        statuses.append({
            "value": value,
            "label": STATUS_LABELS.get(value, value),
            "terminal": len(targets) == 0,
            "allowed_transitions": list(targets),
        })
    return {
        "statuses": statuses,
        "transitions": {key: list(targets) for key, targets in VALID_TRANSITIONS.items()},
        "auto_repair_path": list(AUTO_REPAIR_PATH),
        "cancel_status": "CANCELLED",
    }
