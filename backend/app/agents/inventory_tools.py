"""query_inventory - 库存查询工具

根据设备类型、故障码或关键词查询备件库存，用于工单录入时自动关联备件。
"""
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from app.models.spare_part import SparePart


def query_inventory(
    db: Session,
    device_type: Optional[str] = None,
    fault_code: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 10,
) -> Dict:
    """
    查询备件库存

    Args:
        db: 数据库会话
        device_type: 设备类型过滤
        fault_code: 故障码（按设备类型模糊匹配）
        keyword: 关键词搜索（备件名称/编码）
        limit: 返回数量上限

    Returns:
        {
            "total": int,
            "items": [...],
            "low_stock_items": [...],   # 库存低于安全库存的备件
            "out_of_stock_items": [...], # 已缺货的备件
        }
    """
    query = db.query(SparePart)

    # 按设备类型过滤
    if device_type:
        query = query.filter(SparePart.device_type == device_type)

    # 按关键词搜索
    if keyword:
        query = query.filter(
            SparePart.part_name.ilike(f"%{keyword}%")
            | SparePart.part_code.ilike(f"%{keyword}%")
            | SparePart.specification.ilike(f"%{keyword}%")
        )

    # 如果只指定了 fault_code，尝试从故障码中提取设备类型信息进行匹配
    if fault_code and not device_type and not keyword:
        # 取故障码前缀作为设备类型线索
        code_prefix = fault_code.split("_")[0] if "_" in fault_code else fault_code[:4]
        query = query.filter(SparePart.device_type.ilike(f"%{code_prefix}%"))

    items = query.order_by(SparePart.id.desc()).limit(limit).all()

    # 转换结果
    result_items = []
    low_stock_items = []
    out_of_stock_items = []

    for sp in items:
        item = {
            "id": sp.id,
            "part_code": sp.part_code,
            "part_name": sp.part_name,
            "specification": sp.specification,
            "unit": sp.unit,
            "stock_quantity": sp.stock_quantity,
            "safety_stock": sp.safety_stock,
            "unit_price": sp.unit_price,
            "device_type": sp.device_type,
            "location": sp.location,
            "supplier": sp.supplier,
            "fitment": sp.fitment,
        }
        result_items.append(item)

        if sp.stock_quantity <= 0:
            out_of_stock_items.append(item)
        elif sp.stock_quantity <= sp.safety_stock:
            low_stock_items.append(item)

    return {
        "total": len(result_items),
        "items": result_items,
        "low_stock_items": low_stock_items,
        "out_of_stock_items": out_of_stock_items,
    }


def list_compatible_parts(
    db: Session,
    *,
    brand: Optional[str] = None,
    series: Optional[str] = None,
    year: Optional[int] = None,
    engine: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 20,
):
    """按适配规则筛备件。没有 fitment 的库存不会被算进适配结果。"""
    from app.domain.fitment import part_matches

    query = db.query(SparePart)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            SparePart.part_name.ilike(like)
            | SparePart.part_code.ilike(like)
            | SparePart.specification.ilike(like)
        )
    matched = []
    for part in query.order_by(SparePart.id.desc()).all():
        if part_matches(part.fitment, brand=brand, series=series, year=year, engine=engine):
            matched.append(part)
            if len(matched) >= limit:
                break
    return matched


def resolve_fitment_spec(
    db: Session,
    *,
    vehicle_id: Optional[int] = None,
    plate: Optional[str] = None,
    brand: Optional[str] = None,
    series: Optional[str] = None,
    year: Optional[int] = None,
    engine: Optional[str] = None,
):
    """车辆档案补齐品牌/车系/年款。调用方显式传入的字段优先。"""
    from app.models.vehicle import Vehicle

    spec = {
        "brand": (brand or "").strip(),
        "series": (series or "").strip(),
        "year": year,
        "engine": (engine or "").strip(),
        "vehicle_id": None,
        "plate": (plate or "").strip(),
    }
    vehicle = None
    if vehicle_id:
        vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
        if vehicle is None:
            return None, "车辆不存在"
    elif spec["plate"]:
        vehicle = db.query(Vehicle).filter(Vehicle.plate == spec["plate"]).first()
        if vehicle is None:
            return None, f"未找到车牌 {spec['plate']}"
    if vehicle is not None:
        spec["vehicle_id"] = vehicle.id
        spec["plate"] = vehicle.plate
        if not spec["brand"]:
            spec["brand"] = vehicle.make or ""
        if not spec["series"]:
            spec["series"] = vehicle.model or ""
        if spec["year"] is None:
            spec["year"] = vehicle.year
    return spec, None


def format_compatible_text(spec: dict, parts) -> str:
    from app.domain.fitment import fitment_brief

    head = " ".join(
        str(part) for part in (spec.get("brand"), spec.get("series"), spec.get("year"), spec.get("engine")) if part
    )
    label = head or spec.get("plate") or "该车型"
    if not parts:
        return f"没有找到适配「{label}」的备件。请确认品牌、车系、年款和发动机，或先在备件上维护适配规则。"
    lines = [f"适配「{label}」的备件 {len(parts)} 条："]
    for part in parts:
        unit = part.unit or ""
        lines.append(
            f"- {part.part_name}（{part.part_code}）库存 {part.stock_quantity}{unit}，"
            f"单价 {part.unit_price}。适配：{fitment_brief(part.fitment) or '-'}"
        )
    return "\n".join(lines)
