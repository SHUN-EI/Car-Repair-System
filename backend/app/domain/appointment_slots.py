"""门店可预约时段。

Phase 0 的预约只有一个到店时间，没有独立槽位表。
这里按门店工位和整点生成当天格子，已被待确认/已确认预约占用的格子不可再订。
营业时间写在这里，不新增门店字段，避免再改表。
"""
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Set, Tuple


SLOT_OPEN_HOUR = 9
SLOT_CLOSE_HOUR = 18  # 不含 18 点，最后一格是 17:00
BUSY_APPOINTMENT_STATUSES = ("PENDING", "CONFIRMED")


def slot_starts(day: date) -> List[datetime]:
    """生成指定自然日内、营业时段里每个整点的预约开始时间。

    起止小时由 SLOT_OPEN_HOUR / SLOT_CLOSE_HOUR 决定（结束小时不含）。返回的时间分钟、秒、微秒均为 0。
    """
    return [
        datetime(day.year, day.month, day.day, hour, 0, 0)
        for hour in range(SLOT_OPEN_HOUR, SLOT_CLOSE_HOUR)
    ]


def normalize_slot(value: datetime) -> datetime:
    """把预约时间归一到整点（去掉分、秒、微秒），便于用同一把钥匙判断工位占用冲突。"""
    return value.replace(minute=0, second=0, microsecond=0)


def is_bookable_slot(value: datetime) -> bool:
    """判断时间是否可预约：必须是营业小时内的整点；空值或带分秒的时间返回 False。"""
    if value is None:
        return False
    if value.minute != 0 or value.second != 0 or value.microsecond != 0:
        return False
    return SLOT_OPEN_HOUR <= value.hour < SLOT_CLOSE_HOUR


def build_slot_grid(
    day: date,
    bays: Iterable[dict],
    busy: Optional[Set[Tuple[int, datetime]]] = None,
) -> List[dict]:
    """bays: {id, name, code}。busy: (bay_id, 整点时间)。"""
    occupied = busy or set()
    rows: List[dict] = []
    bay_list = list(bays)
    for start in slot_starts(day):
        for bay in bay_list:
            bay_id = bay["id"]
            rows.append({
                "bay_id": bay_id,
                "bay_name": bay.get("name") or "",
                "bay_code": bay.get("code") or "",
                "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                "available": (bay_id, start) not in occupied,
            })
    return rows


def busy_key(bay_id: Optional[int], scheduled_at: Optional[datetime]) -> Optional[Tuple[int, datetime]]:
    """用工位 ID 和归一化后的预约时间组成占用键。任一参数缺失时返回 None，表示无法参与冲突判断。"""
    if bay_id is None or scheduled_at is None:
        return None
    return bay_id, normalize_slot(scheduled_at)


def group_slots_by_time(slots: List[dict]) -> Dict[str, List[dict]]:
    """按字典里的 start 字段，把工位时段列表归组成「同一开始时间 → 多条工位记录」，供前端按时间展示。"""
    grouped: Dict[str, List[dict]] = {}
    for row in slots:
        grouped.setdefault(row["start"], []).append(row)
    return grouped
