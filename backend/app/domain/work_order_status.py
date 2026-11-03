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
# 门店闭环从预约接车或直接接车进入：APPOINTMENT 不是工单状态，预约核销后落到 INTAKE。
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

# 这些状态只出现在汽修车道。CANCELLED 两边都能到，单靠状态不能区分车道。
AUTO_REPAIR_ONLY_STATUSES = {"INTAKE", "DIAGNOSING", "QUOTING", "QC"}

# 在修期间可以走备件出库。已完成/已结案/已取消不再领料。
PARTS_ISSUE_STATUSES = {
    "INTAKE",
    "DIAGNOSING",
    "QUOTING",
    "APPROVED",
    "IN_PROGRESS",
    "QC",
    "ASSIGNED",
    "ACCEPTED",
    "ARRIVED",
    "INSPECTING",
    "ARCHIVING",
}

# 列表上的下一步按钮文案。键是目标状态。
AUTO_REPAIR_ACTION_LABELS: Dict[str, str] = {
    "INTAKE": "接车",
    "DIAGNOSING": "开始诊断",
    "QUOTING": "出具报价",
    "APPROVED": "确认报价",
    "IN_PROGRESS": "开始施工",
    "QC": "提交质检",
    "COMPLETED": "质检通过",
    "CLOSED": "结案交车",
    "CANCELLED": "取消",
}

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


def is_auto_repair_lane(status=None, vehicle_id=None, appointment_id=None, store_id=None) -> bool:
    """有车辆/预约/门店，或已经走在汽修专有状态上，就按汽修车道处理。

    工业工单没有这些关联，IN_PROGRESS / COMPLETED 仍走原来的派工和归档。
    """
    if vehicle_id or appointment_id or store_id:
        return True
    return status_value(status) in AUTO_REPAIR_ONLY_STATUSES


def next_auto_step(status) -> Optional[str]:
    """汽修主路径的下一步。草稿的下一步是接车。终态没有下一步。"""
    key = status_value(status)
    if key == "DRAFT":
        return "INTAKE"
    if key not in AUTO_REPAIR_PATH:
        return None
    idx = AUTO_REPAIR_PATH.index(key)
    if idx + 1 >= len(AUTO_REPAIR_PATH):
        return None
    return AUTO_REPAIR_PATH[idx + 1]


def parts_issue_allowed(status) -> bool:
    return status_value(status) in PARTS_ISSUE_STATUSES


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
        "auto_repair_actions": dict(AUTO_REPAIR_ACTION_LABELS),
        "cancel_status": "CANCELLED",
    }
