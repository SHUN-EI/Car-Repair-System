"""客户 / 门店 / 工位 / 预约 / 配件目录的骨架接口。

风格对齐设备与备件：分页列表、按 id 读写、登录后访问。
主管只读，和设备台账一致。
"""
from datetime import date, datetime
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app.domain.appointment_slots import (
    BUSY_APPOINTMENT_STATUSES,
    build_slot_grid,
    busy_key,
    is_bookable_slot,
    normalize_slot,
)
from app.domain.appointment_status import (
    APPOINTMENT_STATUSES,
    appointment_targets,
    is_allowed_appointment_transition,
)
from app.domain.owner_access import customer_ids_for_user, ensure_customer_for_user, is_owner
from app.domain.store_scope import StoreScopeError, apply_store_column, ensure_writable_store, resolve_store_scope, role_name, row_in_scope
from app.models.work_order import WorkOrder
from app.models.appointment import Appointment
from app.models.customer import Customer
from app.models.part_sku import PartSku
from app.models.store import Bay, Store
from app.models.user import User
from app.models.vehicle import Vehicle
from pydantic import BaseModel

from app.schemas import (
    AppointmentCreate, AppointmentResponse, AppointmentUpdate,
    BayCreate, BayResponse, BayUpdate,
    CustomerCreate, CustomerResponse, CustomerUpdate,
    PaginatedResponse,
    PartSkuCreate, PartSkuResponse, PartSkuUpdate,
    StoreCreate, StoreResponse, StoreUpdate,
)

customers_router = APIRouter()
stores_router = APIRouter()
bays_router = APIRouter()
appointments_router = APIRouter()
part_skus_router = APIRouter()


def _customer_visible_ids(db: Session, user: User):
    """客户表没有 store_id。店内账号只看本店工单/预约关联的客户，以及尚未分到别的店的客户。"""
    scope = resolve_store_scope(user)
    if scope.mode == "all":
        return None
    here = []
    elsewhere = []
    if scope.mode == "store":
        here = [
            row[0] for row in db.query(Appointment.customer_id).filter(
                Appointment.store_id == scope.store_id, Appointment.customer_id.isnot(None)
            ).all()
        ]
        here += [
            row[0] for row in db.query(WorkOrder.customer_id).filter(
                WorkOrder.store_id == scope.store_id, WorkOrder.customer_id.isnot(None)
            ).all()
        ]
        elsewhere = [
            row[0] for row in db.query(Appointment.customer_id).filter(
                Appointment.store_id.isnot(None),
                Appointment.store_id != scope.store_id,
                Appointment.customer_id.isnot(None),
            ).all()
        ]
        elsewhere += [
            row[0] for row in db.query(WorkOrder.customer_id).filter(
                WorkOrder.store_id.isnot(None),
                WorkOrder.store_id != scope.store_id,
                WorkOrder.customer_id.isnot(None),
            ).all()
        ]
    else:
        elsewhere = [
            row[0] for row in db.query(Appointment.customer_id).filter(
                Appointment.store_id.isnot(None), Appointment.customer_id.isnot(None)
            ).all()
        ]
        elsewhere += [
            row[0] for row in db.query(WorkOrder.customer_id).filter(
                WorkOrder.store_id.isnot(None), WorkOrder.customer_id.isnot(None)
            ).all()
        ]
    return set(here), set(elsewhere)


def _customer_query(query, db: Session, user: User):
    visible = _customer_visible_ids(db, user)
    if visible is None:
        return query
    here, elsewhere = visible
    if elsewhere:
        query = query.filter(~Customer.id.in_(list(elsewhere - here)))
    return query


def _ensure_writer(current_user: User):
    if current_user.role == "SUPERVISOR":
        raise HTTPException(status_code=403, detail="主管仅可查看，如需修改请联系管理员")


def _page(query, page: int, page_size: int):
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return total, items


def _must(db: Session, model, pk: Optional[int], label: str):
    if pk is None:
        return None
    row = db.query(model).filter(model.id == pk).first()
    if not row:
        raise HTTPException(status_code=400, detail=f"{label}不存在")
    return row


def _commit(db: Session, conflict_detail: str):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail=conflict_detail)


# ==================== 客户 ====================

@customers_router.get("/", response_model=PaginatedResponse[CustomerResponse], summary="客户列表")
def list_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _customer_query(db.query(Customer), db, current_user)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(Customer.name.ilike(like) | Customer.phone.ilike(like))
    total, items = _page(query.order_by(Customer.id.desc()), page, page_size)
    return {"total": total, "items": items, "page": page, "page_size": page_size}


@customers_router.get("/{customer_id}", response_model=CustomerResponse, summary="客户详情")
def get_customer(customer_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = _customer_query(db.query(Customer), db, current_user).filter(Customer.id == customer_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="客户不存在")
    return row


@customers_router.post("/", response_model=CustomerResponse, summary="新增客户")
def create_customer(data: CustomerCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    if data.user_id is not None:
        _must(db, User, data.user_id, "关联用户")
    row = Customer(**data.model_dump())
    db.add(row)
    _commit(db, "客户保存失败")
    db.refresh(row)
    return row


@customers_router.put("/{customer_id}", response_model=CustomerResponse, summary="更新客户")
def update_customer(customer_id: int, data: CustomerUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    row = db.query(Customer).filter(Customer.id == customer_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="客户不存在")
    changes = data.model_dump(exclude_unset=True)
    if "user_id" in changes and changes["user_id"] is not None:
        _must(db, User, changes["user_id"], "关联用户")
    for key, val in changes.items():
        setattr(row, key, val)
    _commit(db, "客户保存失败")
    db.refresh(row)
    return row


@customers_router.delete("/{customer_id}", summary="删除客户")
def delete_customer(customer_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    row = db.query(Customer).filter(Customer.id == customer_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="客户不存在")
    db.delete(row)
    _commit(db, "客户已被车辆或预约引用，无法删除")
    return {"message": "客户已删除"}


# ==================== 门店 ====================

@stores_router.get("/", response_model=PaginatedResponse[StoreResponse], summary="门店列表")
def list_stores(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Store)
    scope = resolve_store_scope(current_user)
    if scope.mode == "store":
        query = query.filter(Store.id == scope.store_id)
    elif scope.mode == "legacy":
        query = query.filter(Store.id == -1)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(Store.name.ilike(like) | Store.code.ilike(like))
    total, items = _page(query.order_by(Store.id.desc()), page, page_size)
    return {"total": total, "items": items, "page": page, "page_size": page_size}


@stores_router.get("/context", summary="当前门店")
def store_context(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """店内角色返回绑定门店，不能切换。管理员可以在界面上自选，选择只作为筛选条件。"""
    scope = resolve_store_scope(current_user)
    store = None
    if scope.mode == "store" and scope.store_id:
        store = db.query(Store).filter(Store.id == scope.store_id).first()
    return {
        "role": current_user.role.value if hasattr(current_user.role, "value") else current_user.role,
        "bound_store_id": getattr(current_user, "store_id", None),
        "can_switch": scope.mode == "all" and (current_user.role.value if hasattr(current_user.role, "value") else current_user.role) == "ADMIN",
        "scope": scope.mode,
        "store": None if store is None else {"id": store.id, "code": store.code, "name": store.name},
    }


@stores_router.get("/{store_id}", response_model=StoreResponse, summary="门店详情")
def get_store(store_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = db.query(Store).filter(Store.id == store_id).first()
    if not row or not row_in_scope(resolve_store_scope(current_user), row.id):
        raise HTTPException(status_code=404, detail="门店不存在")
    return row


@stores_router.post("/", response_model=StoreResponse, summary="新增门店")
def create_store(data: StoreCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if role_name(current_user) != "ADMIN":
        raise HTTPException(status_code=403, detail="仅管理员可新增门店")
    code = data.code.strip()
    if db.query(Store.id).filter(Store.code == code).first():
        raise HTTPException(status_code=400, detail="门店编码已存在")
    payload = data.model_dump()
    payload["code"] = code
    row = Store(**payload)
    db.add(row)
    _commit(db, "门店编码已存在")
    db.refresh(row)
    return row


@stores_router.put("/{store_id}", response_model=StoreResponse, summary="更新门店")
def update_store(store_id: int, data: StoreUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    row = db.query(Store).filter(Store.id == store_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="门店不存在")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(row, key, val)
    _commit(db, "门店保存失败")
    db.refresh(row)
    return row


@stores_router.delete("/{store_id}", summary="删除门店")
def delete_store(store_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    row = db.query(Store).filter(Store.id == store_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="门店不存在")
    db.delete(row)
    _commit(db, "门店下仍有工位或预约，无法删除")
    return {"message": "门店已删除"}


# ==================== 工位 ====================

@bays_router.get("/", response_model=PaginatedResponse[BayResponse], summary="工位列表")
def list_bays(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    store_id: Optional[int] = None,
    x_store_id: Optional[str] = Header(None, alias="X-Store-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    requested = store_id
    if requested is None and x_store_id and str(x_store_id).strip().isdigit():
        requested = int(str(x_store_id).strip())
    query = apply_store_column(db.query(Bay), Bay.store_id, resolve_store_scope(current_user, requested))
    total, items = _page(query.order_by(Bay.id.desc()), page, page_size)
    return {"total": total, "items": items, "page": page, "page_size": page_size}


@bays_router.get("/{bay_id}", response_model=BayResponse, summary="工位详情")
def get_bay(bay_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = db.query(Bay).filter(Bay.id == bay_id).first()
    if not row or not row_in_scope(resolve_store_scope(current_user), row.store_id):
        raise HTTPException(status_code=404, detail="工位不存在")
    return row


@bays_router.post("/", response_model=BayResponse, summary="新增工位")
def create_bay(data: BayCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    if not row_in_scope(resolve_store_scope(current_user), data.store_id):
        raise HTTPException(status_code=403, detail="只能操作本门店数据")
    _must(db, Store, data.store_id, "门店")
    code = data.code.strip()
    exists = db.query(Bay.id).filter(Bay.store_id == data.store_id, Bay.code == code).first()
    if exists:
        raise HTTPException(status_code=400, detail="该门店下工位编码已存在")
    payload = data.model_dump()
    payload["code"] = code
    row = Bay(**payload)
    db.add(row)
    _commit(db, "工位编码冲突")
    db.refresh(row)
    return row


@bays_router.put("/{bay_id}", response_model=BayResponse, summary="更新工位")
def update_bay(bay_id: int, data: BayUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    row = db.query(Bay).filter(Bay.id == bay_id).first()
    if not row or not row_in_scope(resolve_store_scope(current_user), row.store_id):
        raise HTTPException(status_code=404, detail="工位不存在")
    changes = data.model_dump(exclude_unset=True)
    if "code" in changes and changes["code"]:
        code = changes["code"].strip()
        exists = db.query(Bay.id).filter(Bay.store_id == row.store_id, Bay.code == code, Bay.id != bay_id).first()
        if exists:
            raise HTTPException(status_code=400, detail="该门店下工位编码已存在")
        changes["code"] = code
    for key, val in changes.items():
        setattr(row, key, val)
    _commit(db, "工位保存失败")
    db.refresh(row)
    return row


@bays_router.delete("/{bay_id}", summary="删除工位")
def delete_bay(bay_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    row = db.query(Bay).filter(Bay.id == bay_id).first()
    if not row or not row_in_scope(resolve_store_scope(current_user), row.store_id):
        raise HTTPException(status_code=404, detail="工位不存在")
    db.delete(row)
    _commit(db, "工位已被预约或工单引用，无法删除")
    return {"message": "工位已删除"}


# ==================== 预约 ====================

class AppointmentBook(BaseModel):
    store_id: int
    bay_id: int
    vehicle_id: int
    scheduled_at: datetime
    remark: Optional[str] = None


@appointments_router.get("/slots", summary="可预约时段")
def list_appointment_slots(
    store_id: int = Query(...),
    day: date = Query(..., description="日期 YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    store = db.query(Store).filter(Store.id == store_id, Store.is_active.is_(True)).first()
    if not store:
        raise HTTPException(status_code=404, detail="门店不存在或未营业")
    bays = (
        db.query(Bay)
        .filter(Bay.store_id == store_id, Bay.is_active.is_(True))
        .order_by(Bay.id.asc())
        .all()
    )
    day_start = datetime(day.year, day.month, day.day)
    day_end = datetime(day.year, day.month, day.day, 23, 59, 59)
    taken = (
        db.query(Appointment)
        .filter(
            Appointment.store_id == store_id,
            Appointment.status.in_(BUSY_APPOINTMENT_STATUSES),
            Appointment.scheduled_at >= day_start,
            Appointment.scheduled_at <= day_end,
        )
        .all()
    )
    busy = set()
    for row in taken:
        key = busy_key(row.bay_id, row.scheduled_at)
        if key:
            busy.add(key)
    slots = build_slot_grid(
        day,
        [{"id": bay.id, "name": bay.name, "code": bay.code} for bay in bays],
        busy,
    )
    return {
        "store_id": store.id,
        "store_name": store.name,
        "date": day.isoformat(),
        "open_hour": 9,
        "close_hour": 18,
        "slots": slots,
    }


@appointments_router.post("/book", response_model=AppointmentResponse, summary="车主预约")
def book_appointment(
    data: AppointmentBook,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "SUPERVISOR":
        raise HTTPException(status_code=403, detail="主管仅可查看预约")
    if not is_bookable_slot(data.scheduled_at):
        raise HTTPException(status_code=400, detail="请选择营业时间内的整点时段（09:00-17:00）")
    vehicle = _must(db, Vehicle, data.vehicle_id, "车辆")
    bay = _must(db, Bay, data.bay_id, "工位")
    if bay.store_id != data.store_id or not bay.is_active:
        raise HTTPException(status_code=400, detail="工位不属于该门店或已停用")
    _must(db, Store, data.store_id, "门店")
    if is_owner(current_user):
        customer = ensure_customer_for_user(db, current_user)
        if vehicle.owner_id != customer.id:
            raise HTTPException(status_code=403, detail="只能预约自己的车辆")
        customer_id = customer.id
    else:
        if not vehicle.owner_id:
            raise HTTPException(status_code=400, detail="车辆还没有车主，请先在车辆档案绑定客户")
        customer_id = vehicle.owner_id
    slot = normalize_slot(data.scheduled_at)
    clash = (
        db.query(Appointment.id)
        .filter(
            Appointment.bay_id == data.bay_id,
            Appointment.status.in_(BUSY_APPOINTMENT_STATUSES),
            Appointment.scheduled_at == slot,
        )
        .first()
    )
    if clash:
        raise HTTPException(status_code=400, detail="该工位时段已被预约")
    row = Appointment(
        store_id=data.store_id,
        bay_id=data.bay_id,
        customer_id=customer_id,
        vehicle_id=vehicle.id,
        scheduled_at=slot,
        status="PENDING",
        remark=(data.remark or "").strip() or None,
    )
    db.add(row)
    _commit(db, "预约保存失败")
    db.refresh(row)
    return _appointment_out(row)

def _appointment_out(row: Appointment) -> AppointmentResponse:
    resp = AppointmentResponse.model_validate(row)
    resp.allowed_transitions = appointment_targets(row.status)
    return resp


def _check_appointment_links(db: Session, store_id: int, bay_id: Optional[int], customer_id: Optional[int], vehicle_id: Optional[int]):
    _must(db, Store, store_id, "门店")
    if bay_id is not None:
        bay = _must(db, Bay, bay_id, "工位")
        if bay.store_id != store_id:
            raise HTTPException(status_code=400, detail="工位不属于该门店")
    if customer_id is not None:
        _must(db, Customer, customer_id, "客户")
    if vehicle_id is not None:
        _must(db, Vehicle, vehicle_id, "车辆")


@appointments_router.get("/", response_model=PaginatedResponse[AppointmentResponse], summary="预约列表")
def list_appointments(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    store_id: Optional[int] = None,
    status: Optional[str] = None,
    x_store_id: Optional[str] = Header(None, alias="X-Store-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Appointment)
    if is_owner(current_user):
        ids = customer_ids_for_user(db, current_user)
        if not ids:
            return {"total": 0, "items": [], "page": page, "page_size": page_size}
        query = query.filter(Appointment.customer_id.in_(ids))
    requested = store_id
    if requested is None and x_store_id and str(x_store_id).strip().isdigit():
        requested = int(str(x_store_id).strip())
    query = apply_store_column(query, Appointment.store_id, resolve_store_scope(current_user, requested))
    if status:
        query = query.filter(Appointment.status == status.upper())
    total, items = _page(query.order_by(Appointment.scheduled_at.desc()), page, page_size)
    return {
        "total": total,
        "items": [_appointment_out(row) for row in items],
        "page": page,
        "page_size": page_size,
    }


@appointments_router.get("/{appointment_id}", response_model=AppointmentResponse, summary="预约详情")
def get_appointment(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="预约不存在")
    if not is_owner(current_user) and not row_in_scope(resolve_store_scope(current_user), row.store_id):
        raise HTTPException(status_code=404, detail="预约不存在")
    return _appointment_out(row)


@appointments_router.post("/", response_model=AppointmentResponse, summary="新增预约")
def create_appointment(data: AppointmentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    try:
        store_id = ensure_writable_store(current_user, data.store_id)
    except StoreScopeError as exc:
        raise HTTPException(status_code=403, detail=exc.message)
    if store_id is None:
        raise HTTPException(status_code=403, detail="当前账号未绑定门店，不能新建预约")
    payload = data.model_dump()
    payload["store_id"] = store_id
    _check_appointment_links(db, payload["store_id"], payload.get("bay_id"), payload.get("customer_id"), payload.get("vehicle_id"))
    row = Appointment(**payload, status="PENDING")
    db.add(row)
    _commit(db, "预约保存失败")
    db.refresh(row)
    return _appointment_out(row)


@appointments_router.put("/{appointment_id}", response_model=AppointmentResponse, summary="更新预约")
def update_appointment(
    appointment_id: int,
    data: AppointmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_writer(current_user)
    row = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not row or not row_in_scope(resolve_store_scope(current_user), row.store_id):
        raise HTTPException(status_code=404, detail="预约不存在")
    changes = data.model_dump(exclude_unset=True)
    next_status = changes.pop("status", None)
    if next_status is not None:
        next_status = next_status.upper()
        if next_status not in APPOINTMENT_STATUSES:
            raise HTTPException(status_code=400, detail=f"无效的预约状态: {next_status}")
        if not is_allowed_appointment_transition(row.status, next_status):
            raise HTTPException(
                status_code=400,
                detail=f"非法预约流转: {row.status} → {next_status}，允许: {appointment_targets(row.status)}",
            )
        row.status = next_status
    store_id = row.store_id
    bay_id = changes.get("bay_id", row.bay_id)
    customer_id = changes.get("customer_id", row.customer_id)
    vehicle_id = changes.get("vehicle_id", row.vehicle_id)
    if any(key in changes for key in ("bay_id", "customer_id", "vehicle_id")):
        _check_appointment_links(db, store_id, bay_id, customer_id, vehicle_id)
    for key, val in changes.items():
        setattr(row, key, val)
    _commit(db, "预约保存失败")
    db.refresh(row)
    return _appointment_out(row)


@appointments_router.delete("/{appointment_id}", summary="删除预约")
def delete_appointment(appointment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    row = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not row or not row_in_scope(resolve_store_scope(current_user), row.store_id):
        raise HTTPException(status_code=404, detail="预约不存在")
    db.delete(row)
    _commit(db, "预约已被工单引用，无法删除")
    return {"message": "预约已删除"}


# ==================== 配件目录 SKU ====================

@part_skus_router.get("/", response_model=PaginatedResponse[PartSkuResponse], summary="配件目录列表")
def list_part_skus(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    keyword: Optional[str] = None,
    brand: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(PartSku)
    if brand:
        query = query.filter(PartSku.brand == brand)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            PartSku.code.ilike(like) | PartSku.name.ilike(like) | PartSku.brand.ilike(like)
        )
    total, items = _page(query.order_by(PartSku.id.desc()), page, page_size)
    return {"total": total, "items": items, "page": page, "page_size": page_size}


@part_skus_router.get("/{sku_id}", response_model=PartSkuResponse, summary="配件目录详情")
def get_part_sku(sku_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = db.query(PartSku).filter(PartSku.id == sku_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="配件目录不存在")
    return row


@part_skus_router.post("/", response_model=PartSkuResponse, summary="新增配件目录")
def create_part_sku(data: PartSkuCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    code = data.code.strip()
    if db.query(PartSku.id).filter(PartSku.code == code).first():
        raise HTTPException(status_code=400, detail="SKU 编码已存在")
    payload = data.model_dump()
    payload["code"] = code
    row = PartSku(**payload)
    db.add(row)
    _commit(db, "SKU 编码已存在")
    db.refresh(row)
    return row


@part_skus_router.put("/{sku_id}", response_model=PartSkuResponse, summary="更新配件目录")
def update_part_sku(sku_id: int, data: PartSkuUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    row = db.query(PartSku).filter(PartSku.id == sku_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="配件目录不存在")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(row, key, val)
    _commit(db, "配件目录保存失败")
    db.refresh(row)
    return row


@part_skus_router.delete("/{sku_id}", summary="删除配件目录")
def delete_part_sku(sku_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    row = db.query(PartSku).filter(PartSku.id == sku_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="配件目录不存在")
    db.delete(row)
    _commit(db, "SKU 已被备件库存引用，无法删除")
    return {"message": "配件目录已删除"}
