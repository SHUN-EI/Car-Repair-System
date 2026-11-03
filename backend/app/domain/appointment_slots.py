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
    return [
        datetime(day.year, day.month, day.day, hour, 0, 0)
        for hour in range(SLOT_OPEN_HOUR, SLOT_CLOSE_HOUR)
    ]


def normalize_slot(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def is_bookable_slot(value: datetime) -> bool:
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
    if bay_id is None or scheduled_at is None:
        return None
    return bay_id, normalize_slot(scheduled_at)


def group_slots_by_time(slots: List[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {}
    for row in slots:
        grouped.setdefault(row["start"], []).append(row)
    return grouped
