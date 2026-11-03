"""保养套餐推荐。供 API 和 MCP 共用，规则在 domain.service_recommend。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.domain.service_recommend import rank_offers
from app.models.service_catalog import ServicePackage, ServiceSku
from app.models.vehicle import Vehicle


def _vehicle_spec(db: Session, vehicle_id: Optional[int], plate: Optional[str], brand: Optional[str], series: Optional[str]):
    vehicle = None
    if vehicle_id:
        vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
        if vehicle is None:
            return None, "车辆不存在"
    elif plate:
        vehicle = db.query(Vehicle).filter(Vehicle.plate == plate.strip()).first()
        if vehicle is None:
            return None, f"未找到车牌 {plate}"
    spec = {
        "brand": (brand or "").strip(),
        "series": (series or "").strip(),
        "year": None,
        "vehicle_id": None,
        "plate": plate or "",
    }
    if vehicle is not None:
        spec["vehicle_id"] = vehicle.id
        spec["plate"] = vehicle.plate
        spec["year"] = vehicle.year
        if not spec["brand"]:
            spec["brand"] = vehicle.make or ""
        if not spec["series"]:
            spec["series"] = vehicle.model or ""
    return spec, None


def _package_dict(row: ServicePackage) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "description": row.description,
        "brand": row.brand,
        "series": row.series,
        "mileage_from": row.mileage_from,
        "mileage_to": row.mileage_to,
        "symptom_keywords": row.symptom_keywords,
        "list_price": row.list_price or 0,
        "is_active": row.is_active,
    }


def _sku_dict(row: ServiceSku) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "labor_minutes": row.labor_minutes or 0,
        "base_price": row.base_price or 0,
        "package_id": row.package_id,
        "category": row.category,
        "symptom_keywords": row.symptom_keywords,
        "brand": row.brand,
        "series": row.series,
        "mileage_from": row.mileage_from,
        "mileage_to": row.mileage_to,
        "is_active": row.is_active,
    }


def recommend_service_packages(
    db: Session,
    *,
    vehicle_id: Optional[int] = None,
    plate: Optional[str] = None,
    brand: Optional[str] = None,
    series: Optional[str] = None,
    mileage: Optional[int] = None,
    symptoms: Optional[str] = None,
) -> dict:
    spec, error = _vehicle_spec(db, vehicle_id, plate, brand, series)
    if error:
        return {"vehicle": None, "packages": [], "skus": [], "note": error}
    packages = rank_offers(
        [_package_dict(row) for row in db.query(ServicePackage).all()],
        brand=spec["brand"],
        series=spec["series"],
        mileage=mileage,
        symptoms=symptoms,
    )
    skus = rank_offers(
        [_sku_dict(row) for row in db.query(ServiceSku).all()],
        brand=spec["brand"],
        series=spec["series"],
        mileage=mileage,
        symptoms=symptoms,
    )
    package_ids = {row["id"] for row in packages}
    standalone = [row for row in skus if not row.get("package_id") or row.get("package_id") not in package_ids]
    for package in packages:
        package["skus"] = [row for row in skus if row.get("package_id") == package["id"]]
    note = ""
    if not packages and not standalone:
        note = "没有符合该车型或里程的保养套餐和项目"
    return {
        "vehicle": {
            "id": spec["vehicle_id"],
            "plate": spec["plate"] or None,
            "brand": spec["brand"] or None,
            "series": spec["series"] or None,
            "year": spec["year"],
            "mileage": mileage,
        },
        "packages": packages,
        "skus": standalone,
        "note": note,
    }


def format_recommendation(result: dict) -> str:
    if result.get("note") and not result.get("packages") and not result.get("skus"):
        return result["note"]
    vehicle = result.get("vehicle") or {}
    head = " ".join(
        str(part) for part in (vehicle.get("brand"), vehicle.get("series"), vehicle.get("year")) if part
    )
    mileage = vehicle.get("mileage")
    title = f"保养推荐（{head or '未指定车型'}"
    if mileage is not None:
        title += f"，{mileage}km"
    title += "）"
    lines = [title]
    if not result.get("packages") and not result.get("skus"):
        lines.append(result.get("note") or "没有符合条件的套餐。")
        return "\n".join(lines)
    for package in result.get("packages") or []:
        lines.append(
            f"- 套餐 {package.get('name')}（{package.get('code')}）"
            f" {package.get('list_price')} 元。{package.get('reason') or ''}"
        )
        for sku in package.get("skus") or []:
            lines.append(f"  · {sku.get('name')} {sku.get('base_price')} 元 / {sku.get('labor_minutes') or 0} 分钟")
    for sku in result.get("skus") or []:
        lines.append(
            f"- 项目 {sku.get('name')}（{sku.get('code')}）"
            f" {sku.get('base_price')} 元。{sku.get('reason') or ''}"
        )
    if result.get("note"):
        lines.append(result["note"])
    return "\n".join(lines)
