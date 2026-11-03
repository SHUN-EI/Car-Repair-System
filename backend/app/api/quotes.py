"""报价草案、店员确认、车主确认。"""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app.domain.owner_access import customer_ids_for_user, is_owner
from app.domain.owner_notify import notify_owner
from app.domain.quote_service import QuoteError, add_manual_line, apply_status, create_draft, delete_line
from app.domain.quote_status import QUOTE_LABELS, QUOTE_TRANSITIONS
from app.domain.store_scope import StoreScopeError, apply_store_column, ensure_writable_store, resolve_store_scope, row_in_scope
from app.models.quote import Quote
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas import (
    CustomerConfirmRequest,
    PaginatedResponse,
    QuoteActionResponse,
    QuoteDraftRequest,
    QuoteLineCreate,
    QuoteResponse,
)

router = APIRouter()


def _role(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role or "")


def _staff(user: User) -> bool:
    return _role(user) in {"ADMIN", "SUPERVISOR", "TECHNICIAN"}


def _can_staff_confirm(user: User) -> bool:
    return _role(user) in {"ADMIN", "SUPERVISOR"}


def _raise_quote(exc: QuoteError):
    raise HTTPException(status_code=exc.status_code, detail=str(exc))


def _to_response(quote: Quote, notify: Optional[dict] = None):
    payload = QuoteResponse(
        id=quote.id,
        quote_no=quote.quote_no,
        work_order_id=quote.work_order_id,
        vehicle_id=quote.vehicle_id,
        customer_id=quote.customer_id,
        store_id=quote.store_id,
        status=quote.status,
        status_label=QUOTE_LABELS.get(quote.status, quote.status),
        customer_confirm=bool(quote.customer_confirm),
        total=quote.total or 0,
        mileage=quote.mileage,
        symptoms=quote.symptoms,
        consult_text=quote.consult_text,
        note=quote.note,
        lines=list(quote.lines or []),
        allowed_transitions=list(QUOTE_TRANSITIONS.get(quote.status, [])),
        created_at=quote.created_at,
        updated_at=quote.updated_at,
    )
    if notify is None:
        return payload
    return QuoteActionResponse(**payload.model_dump(), notify=notify)


def _get_quote(db: Session, quote_id: int) -> Quote:
    row = db.query(Quote).filter(Quote.id == quote_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="报价单不存在")
    return row


def _owner_can_see(db: Session, user: User, quote: Quote) -> bool:
    ids = set(customer_ids_for_user(db, user))
    if quote.customer_id and quote.customer_id in ids:
        return True
    if quote.vehicle_id:
        vehicle = db.query(Vehicle).filter(Vehicle.id == quote.vehicle_id).first()
        if vehicle and vehicle.owner_id in ids:
            return True
    return False


def _quote_scope(user: User, store_id: Optional[int] = None, x_store_id: Optional[str] = None):
    requested = store_id
    if requested is None and x_store_id and str(x_store_id).strip().isdigit():
        requested = int(str(x_store_id).strip())
    try:
        return resolve_store_scope(user, requested)
    except StoreScopeError as exc:
        raise HTTPException(status_code=403, detail=exc.message)


def _ensure_visible(db: Session, user: User, quote: Quote):
    if is_owner(user) and not _owner_can_see(db, user, quote):
        raise HTTPException(status_code=404, detail="报价单不存在")
    if not row_in_scope(_quote_scope(user), quote.store_id):
        raise HTTPException(status_code=404, detail="报价单不存在")


@router.get("/", response_model=PaginatedResponse[QuoteResponse], summary="报价单列表")
def list_quotes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    work_order_id: Optional[int] = None,
    status: Optional[str] = None,
    store_id: Optional[int] = None,
    x_store_id: Optional[str] = Header(None, alias="X-Store-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = apply_store_column(db.query(Quote), Quote.store_id, _quote_scope(current_user, store_id, x_store_id))
    if work_order_id:
        query = query.filter(Quote.work_order_id == work_order_id)
    if status:
        query = query.filter(Quote.status == status.strip().upper())
    if is_owner(current_user):
        ids = customer_ids_for_user(db, current_user)
        vehicle_ids = []
        if ids:
            vehicle_ids = [row.id for row in db.query(Vehicle.id).filter(Vehicle.owner_id.in_(ids)).all()]
        if not ids and not vehicle_ids:
            return {"total": 0, "items": [], "page": page, "page_size": page_size}
        filters = []
        if ids:
            filters.append(Quote.customer_id.in_(ids))
        if vehicle_ids:
            filters.append(Quote.vehicle_id.in_(vehicle_ids))
        query = query.filter(or_(*filters))
    total = query.count()
    items = query.order_by(Quote.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [_to_response(row) for row in items], "page": page, "page_size": page_size}


@router.post("/draft", response_model=QuoteResponse, summary="生成报价草案")
def draft_quote(
    data: QuoteDraftRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _staff(current_user):
        raise HTTPException(status_code=403, detail="车主不能出具报价")
    if data.work_order_id:
        from app.models.work_order import WorkOrder
        work_order = db.query(WorkOrder).filter(WorkOrder.id == data.work_order_id).first()
        if work_order and not row_in_scope(_quote_scope(current_user), work_order.store_id):
            raise HTTPException(status_code=404, detail="工单不存在")
        try:
            ensure_writable_store(current_user, work_order.store_id if work_order else None)
        except StoreScopeError as exc:
            raise HTTPException(status_code=403, detail=exc.message)
    try:
        quote = create_draft(
            db,
            work_order_id=data.work_order_id,
            vehicle_id=data.vehicle_id,
            consult_text=data.consult_text,
            suggestions=[item.model_dump() for item in data.suggestions] if data.suggestions else None,
            mileage=data.mileage,
            symptoms=data.symptoms,
            include_packages=data.include_packages,
            include_used_parts=data.include_used_parts,
            created_by=current_user.id,
        )
    except QuoteError as exc:
        _raise_quote(exc)
    scope = _quote_scope(current_user)
    if scope.mode == "store" and quote.store_id is None:
        quote.store_id = scope.store_id
        db.commit()
        db.refresh(quote)
    return _to_response(quote)


@router.get("/{quote_id}", response_model=QuoteResponse, summary="报价单详情")
def get_quote(quote_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    quote = _get_quote(db, quote_id)
    _ensure_visible(db, current_user, quote)
    return _to_response(quote)


@router.post("/{quote_id}/lines", response_model=QuoteResponse, summary="草案追加明细")
def create_line(
    quote_id: int,
    data: QuoteLineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _staff(current_user):
        raise HTTPException(status_code=403, detail="车主不能修改报价明细")
    quote = _get_quote(db, quote_id)
    try:
        quote = add_manual_line(db, quote, data.model_dump())
    except QuoteError as exc:
        _raise_quote(exc)
    return _to_response(quote)


@router.delete("/{quote_id}/lines/{line_id}", response_model=QuoteResponse, summary="删除草案明细")
def remove_line(
    quote_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _staff(current_user):
        raise HTTPException(status_code=403, detail="车主不能修改报价明细")
    quote = _get_quote(db, quote_id)
    try:
        quote = delete_line(db, quote, line_id)
    except QuoteError as exc:
        _raise_quote(exc)
    return _to_response(quote)


def _after_status(db: Session, quote: Quote, label: str, title: str):
    return notify_owner(
        db,
        customer_id=quote.customer_id,
        vehicle_id=quote.vehicle_id,
        work_order_id=quote.work_order_id,
        work_order_no=quote.quote_no,
        status_label=label,
        title=title,
    )


@router.post("/{quote_id}/staff-confirm", response_model=QuoteActionResponse, summary="店员确认报价")
def staff_confirm(quote_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not _can_staff_confirm(current_user):
        raise HTTPException(status_code=403, detail="仅主管或管理员可确认报价")
    quote = _get_quote(db, quote_id)
    try:
        quote = apply_status(db, quote, "STAFF_CONFIRMED", user_id=current_user.id)
    except QuoteError as exc:
        _raise_quote(exc)
    notify = _after_status(db, quote, "报价待车主确认", f"报价待确认 {quote.quote_no}")
    return _to_response(quote, notify)


@router.post("/{quote_id}/customer-confirm", response_model=QuoteActionResponse, summary="车主确认报价")
def customer_confirm(
    quote_id: int,
    data: Optional[CustomerConfirmRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = data or CustomerConfirmRequest()
    quote = _get_quote(db, quote_id)
    if is_owner(current_user):
        if not _owner_can_see(db, current_user, quote):
            raise HTTPException(status_code=404, detail="报价单不存在")
    elif data.on_behalf and _can_staff_confirm(current_user):
        pass
    else:
        raise HTTPException(status_code=403, detail="请由车主确认，或由主管代录车主确认")
    try:
        quote = apply_status(db, quote, "CUSTOMER_CONFIRMED", user_id=current_user.id)
    except QuoteError as exc:
        _raise_quote(exc)
    label = "车主已确认报价" if not data.on_behalf else "店员已代录车主确认"
    notify = _after_status(db, quote, label, f"报价已确认 {quote.quote_no}")
    return _to_response(quote, notify)


@router.post("/{quote_id}/reject", response_model=QuoteActionResponse, summary="拒绝报价")
def reject_quote(quote_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    quote = _get_quote(db, quote_id)
    if is_owner(current_user):
        if not _owner_can_see(db, current_user, quote):
            raise HTTPException(status_code=404, detail="报价单不存在")
    elif not _can_staff_confirm(current_user):
        raise HTTPException(status_code=403, detail="仅车主、主管或管理员可拒绝报价")
    try:
        quote = apply_status(db, quote, "REJECTED", user_id=current_user.id)
    except QuoteError as exc:
        _raise_quote(exc)
    notify = _after_status(db, quote, "报价已拒绝", f"报价已拒绝 {quote.quote_no}")
    return _to_response(quote, notify)


@router.post("/{quote_id}/cancel", response_model=QuoteResponse, summary="取消报价")
def cancel_quote(quote_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not _staff(current_user):
        raise HTTPException(status_code=403, detail="车主不能取消报价单，如需拒绝请使用拒绝")
    quote = _get_quote(db, quote_id)
    try:
        quote = apply_status(db, quote, "CANCELLED", user_id=current_user.id)
    except QuoteError as exc:
        _raise_quote(exc)
    return _to_response(quote)
