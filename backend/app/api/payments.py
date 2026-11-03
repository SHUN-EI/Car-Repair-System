"""支付意向占位。只落本地单据，不调用任何支付渠道。"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app.domain.owner_access import customer_ids_for_user, is_owner
from app.domain.payment_status import PAYMENT_CHANNEL, PAYMENT_LABELS
from app.models.payment import PaymentIntent
from app.models.quote import Quote
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas import PaginatedResponse, PaymentIntentCreate, PaymentIntentResponse

router = APIRouter()


def _role(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role or "")


def _to_response(row: PaymentIntent, reused: bool = False) -> PaymentIntentResponse:
    return PaymentIntentResponse(
        id=row.id,
        intent_no=row.intent_no,
        quote_id=row.quote_id,
        work_order_id=row.work_order_id,
        amount=row.amount or 0,
        currency=row.currency,
        channel=row.channel,
        status=row.status,
        status_label=PAYMENT_LABELS.get(row.status, row.status),
        note=row.note,
        reused=reused,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/intents/", response_model=PaginatedResponse[PaymentIntentResponse], summary="支付意向列表")
def list_intents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    quote_id: Optional[int] = None,
    work_order_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(PaymentIntent)
    if quote_id:
        query = query.filter(PaymentIntent.quote_id == quote_id)
    if work_order_id:
        query = query.filter(PaymentIntent.work_order_id == work_order_id)
    if is_owner(current_user):
        ids = customer_ids_for_user(db, current_user)
        vehicle_ids = [
            row.id for row in db.query(Vehicle.id).filter(Vehicle.owner_id.in_(ids)).all()
        ] if ids else []
        filters = []
        if ids:
            filters.append(Quote.customer_id.in_(ids))
        if vehicle_ids:
            filters.append(Quote.vehicle_id.in_(vehicle_ids))
        owned = [row.id for row in db.query(Quote.id).filter(or_(*filters)).all()] if filters else []
        query = query.filter(PaymentIntent.quote_id.in_(owned or [-1]))
    total = query.count()
    items = query.order_by(PaymentIntent.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "items": [_to_response(row) for row in items],
        "page": page,
        "page_size": page_size,
    }


@router.post("/intents/", response_model=PaymentIntentResponse, summary="创建支付意向（不清算）")
def create_intent(
    data: PaymentIntentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if _role(current_user) not in {"ADMIN", "SUPERVISOR", "TECHNICIAN", "OWNER"}:
        raise HTTPException(status_code=403, detail="当前角色不能创建支付意向")
    quote = db.query(Quote).filter(Quote.id == data.quote_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="报价单不存在")
    if quote.status != "CUSTOMER_CONFIRMED" or not quote.customer_confirm:
        raise HTTPException(status_code=400, detail="车主尚未确认报价，不能创建支付意向")
    existing = (
        db.query(PaymentIntent)
        .filter(PaymentIntent.quote_id == quote.id, PaymentIntent.status == "CREATED")
        .order_by(PaymentIntent.id.desc())
        .first()
    )
    if existing:
        return _to_response(existing, reused=True)
    intent_no = "PI-" + datetime.utcnow().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8].upper()
    row = PaymentIntent(
        intent_no=intent_no,
        quote_id=quote.id,
        work_order_id=quote.work_order_id,
        amount=quote.total or 0,
        currency="CNY",
        channel=PAYMENT_CHANNEL,
        status="CREATED",
        note="占位订单，未接入清算",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_response(row)


@router.get("/intents/{intent_id}", response_model=PaymentIntentResponse, summary="支付意向详情")
def get_intent(intent_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = db.query(PaymentIntent).filter(PaymentIntent.id == intent_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="支付意向不存在")
    return _to_response(row)


@router.post("/intents/{intent_id}/cancel", response_model=PaymentIntentResponse, summary="取消支付意向")
def cancel_intent(intent_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if _role(current_user) not in {"ADMIN", "SUPERVISOR"}:
        raise HTTPException(status_code=403, detail="仅主管或管理员可取消支付意向")
    row = db.query(PaymentIntent).filter(PaymentIntent.id == intent_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="支付意向不存在")
    if row.status != "CREATED":
        raise HTTPException(status_code=400, detail="该支付意向已取消")
    row.status = "CANCELLED"
    row.note = "占位订单已取消，未发生清算"
    db.commit()
    db.refresh(row)
    return _to_response(row)
