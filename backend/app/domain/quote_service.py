"""报价草案的组装和状态推进。角色校验放在 API 层。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.domain.quote_lines import build_quote_lines
from app.domain.quote_status import QUOTE_LABELS, can_transition
from app.domain.service_recommend import rank_offers
from app.models.quote import Quote, QuoteLine
from app.models.service_catalog import ServicePackage, ServiceSku
from app.models.spare_part import SparePart
from app.models.vehicle import Vehicle
from app.models.work_order import WorkOrder


class QuoteError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _next_quote_no(db: Session) -> str:
    prefix = "QT-" + datetime.utcnow().strftime("%Y%m%d") + "-"
    latest = (
        db.query(Quote)
        .filter(Quote.quote_no.like(f"{prefix}%"))
        .order_by(Quote.quote_no.desc())
        .first()
    )
    seq = 1
    if latest and latest.quote_no:
        try:
            seq = int(latest.quote_no.split("-")[-1]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:03d}"


def _sku_row(row: ServiceSku) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "base_price": row.base_price or 0,
        "package_id": row.package_id,
        "brand": row.brand,
        "series": row.series,
        "mileage_from": row.mileage_from,
        "mileage_to": row.mileage_to,
        "symptom_keywords": row.symptom_keywords,
        "is_active": row.is_active,
        "labor_minutes": row.labor_minutes,
        "category": row.category,
    }


def _package_row(row: ServicePackage) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "list_price": row.list_price or 0,
        "brand": row.brand,
        "series": row.series,
        "mileage_from": row.mileage_from,
        "mileage_to": row.mileage_to,
        "symptom_keywords": row.symptom_keywords,
        "is_active": row.is_active,
        "description": row.description,
    }


def _recalc(quote: Quote) -> None:
    total = 0.0
    ordered = sorted(list(quote.lines or []), key=lambda row: row.line_no or 0)
    for index, line in enumerate(ordered, start=1):
        line.line_no = index
        line.amount = round(float(line.qty or 0) * float(line.unit_price or 0), 2)
        total += line.amount
    quote.total = round(total, 2)


def create_draft(
    db: Session,
    *,
    work_order_id: Optional[int] = None,
    vehicle_id: Optional[int] = None,
    consult_text: Optional[str] = None,
    suggestions: Optional[list] = None,
    mileage: Optional[int] = None,
    symptoms: Optional[str] = None,
    include_packages: bool = False,
    include_used_parts: bool = True,
    created_by: Optional[int] = None,
) -> Quote:
    work_order = None
    if work_order_id:
        work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
        if not work_order:
            raise QuoteError("工单不存在", 404)
    resolved_vehicle_id = vehicle_id or (work_order.vehicle_id if work_order else None)
    vehicle = None
    if resolved_vehicle_id:
        vehicle = db.query(Vehicle).filter(Vehicle.id == resolved_vehicle_id).first()
        if vehicle_id and not vehicle:
            raise QuoteError("车辆不存在", 404)

    brand = vehicle.make if vehicle else ""
    series = vehicle.model if vehicle else ""
    parts = db.query(SparePart).all()
    part_prices = {row.part_code: row.unit_price or 0 for row in parts}
    part_catalog = [
        {"id": row.id, "code": row.part_code, "name": row.part_name, "unit_price": row.unit_price or 0}
        for row in parts
    ]
    sku_models = db.query(ServiceSku).filter(ServiceSku.is_active.is_(True)).all()
    service_catalog = [_sku_row(row) for row in sku_models]
    packages = []
    if include_packages:
        package_models = db.query(ServicePackage).filter(ServicePackage.is_active.is_(True)).all()
        packages = rank_offers(
            [_package_row(row) for row in package_models],
            brand=brand,
            series=series,
            mileage=mileage,
            symptoms=symptoms or consult_text or "",
        )

    used = list(work_order.used_parts or []) if work_order and include_used_parts else []
    line_rows, note = build_quote_lines(
        used_parts=used,
        part_prices=part_prices,
        part_catalog=part_catalog,
        consult_text=consult_text,
        suggestions=suggestions,
        packages=packages,
        service_catalog=service_catalog,
        include_used_parts=include_used_parts,
        include_packages=include_packages,
    )
    if not line_rows:
        raise QuoteError(note or "没有可写入报价的项目")

    customer_id = None
    store_id = None
    if work_order:
        customer_id = work_order.customer_id
        store_id = work_order.store_id
    if vehicle and vehicle.owner_id and not customer_id:
        customer_id = vehicle.owner_id

    quote = Quote(
        quote_no=_next_quote_no(db),
        work_order_id=work_order.id if work_order else None,
        vehicle_id=vehicle.id if vehicle else None,
        customer_id=customer_id,
        store_id=store_id,
        status="DRAFT",
        customer_confirm=False,
        mileage=mileage,
        symptoms=(symptoms or None),
        consult_text=(consult_text or None),
        note=note or None,
        created_by=created_by,
        total=0,
    )
    db.add(quote)
    db.flush()
    for item in line_rows:
        db.add(QuoteLine(quote_id=quote.id, **item))
    db.flush()
    db.refresh(quote)
    _recalc(quote)
    db.commit()
    db.refresh(quote)
    return quote


def apply_status(db: Session, quote: Quote, to_status: str, *, user_id: Optional[int] = None) -> Quote:
    if not can_transition(quote.status, to_status):
        src = QUOTE_LABELS.get(quote.status, quote.status)
        dest = QUOTE_LABELS.get(to_status, to_status)
        raise QuoteError(f"报价不能从{src}转为{dest}")
    quote.status = to_status
    if to_status == "STAFF_CONFIRMED":
        quote.staff_confirmed_by = user_id
        quote.customer_confirm = False
    elif to_status == "CUSTOMER_CONFIRMED":
        quote.customer_confirm = True
        quote.customer_confirmed_at = datetime.utcnow()
    elif to_status in ("REJECTED", "CANCELLED"):
        quote.customer_confirm = False
    db.commit()
    db.refresh(quote)
    return quote


def add_manual_line(db: Session, quote: Quote, payload: dict) -> Quote:
    if quote.status != "DRAFT":
        raise QuoteError("只有草案可以改明细")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise QuoteError("请填写项目名称")
    qty = float(payload.get("qty") or 0)
    if qty <= 0:
        raise QuoteError("数量必须大于 0")
    line_type = str(payload.get("line_type") or "LABOR").upper()
    if line_type not in ("PART", "LABOR", "PACKAGE"):
        raise QuoteError("明细类型只能是配件、工时或套餐")
    db.add(QuoteLine(
        quote_id=quote.id,
        line_no=len(quote.lines or []) + 1,
        line_type=line_type,
        name=name[:200],
        code=(str(payload.get("code")).strip()[:50] if payload.get("code") else None),
        qty=qty,
        unit_price=float(payload.get("unit_price") or 0),
        amount=0,
        source="manual",
        ref_id=payload.get("ref_id"),
    ))
    db.flush()
    db.refresh(quote)
    _recalc(quote)
    db.commit()
    db.refresh(quote)
    return quote


def delete_line(db: Session, quote: Quote, line_id: int) -> Quote:
    if quote.status != "DRAFT":
        raise QuoteError("只有草案可以改明细")
    line = next((row for row in quote.lines or [] if row.id == line_id), None)
    if line is None:
        raise QuoteError("报价明细不存在", 404)
    db.delete(line)
    db.flush()
    db.refresh(quote)
    _recalc(quote)
    db.commit()
    db.refresh(quote)
    return quote
