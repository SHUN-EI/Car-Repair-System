"""车辆档案 CRUD。车主是客户，不是系统用户。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app.domain.owner_access import customer_ids_for_user, ensure_customer_for_user, is_owner
from app.models.customer import Customer
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas import VehicleCreate, VehicleUpdate, VehicleResponse, PaginatedResponse

router = APIRouter()


def _ensure_writer(current_user: User):
    if current_user.role == "SUPERVISOR":
        raise HTTPException(status_code=403, detail="主管仅可查看车辆，如需修改请联系管理员")


def _norm_plate(plate: str) -> str:
    value = (plate or "").strip().upper().replace(" ", "")
    if not value:
        raise HTTPException(status_code=400, detail="车牌号不能为空")
    return value


def _norm_vin(vin: Optional[str]) -> Optional[str]:
    if vin is None:
        return None
    value = vin.strip().upper()
    if not value:
        return None
    if len(value) != 17 or not value.isalnum():
        raise HTTPException(status_code=400, detail="VIN 需为 17 位字母或数字")
    return value


def _ensure_owner(db: Session, owner_id: Optional[int]):
    if owner_id is None:
        return
    if not db.query(Customer.id).filter(Customer.id == owner_id).first():
        raise HTTPException(status_code=400, detail="车主客户不存在")


def _to_response(vehicle: Vehicle, owner_name: Optional[str] = None) -> VehicleResponse:
    resp = VehicleResponse.model_validate(vehicle)
    resp.owner_name = owner_name
    return resp


@router.get("/", response_model=PaginatedResponse[VehicleResponse], summary="车辆列表")
def list_vehicles(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    keyword: Optional[str] = None,
    owner_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Vehicle)
    if is_owner(current_user):
        ids = customer_ids_for_user(db, current_user)
        if not ids:
            return {"total": 0, "items": [], "page": page, "page_size": page_size}
        query = query.filter(Vehicle.owner_id.in_(ids))
    elif owner_id:
        query = query.filter(Vehicle.owner_id == owner_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            Vehicle.plate.ilike(like)
            | Vehicle.vin.ilike(like)
            | Vehicle.make.ilike(like)
            | Vehicle.model.ilike(like)
        )
    total = query.count()
    items = query.order_by(Vehicle.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    owner_ids = {v.owner_id for v in items if v.owner_id}
    owner_names = {}
    if owner_ids:
        for row in db.query(Customer).filter(Customer.id.in_(owner_ids)).all():
            owner_names[row.id] = row.name
    return {
        "total": total,
        "items": [_to_response(v, owner_names.get(v.owner_id)) for v in items],
        "page": page,
        "page_size": page_size,
    }


@router.get("/{vehicle_id}", response_model=VehicleResponse, summary="车辆详情")
def get_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="车辆不存在")
    if is_owner(current_user):
        ids = set(customer_ids_for_user(db, current_user))
        if vehicle.owner_id not in ids:
            raise HTTPException(status_code=404, detail="车辆不存在")
    owner_name = None
    if vehicle.owner_id:
        owner = db.query(Customer).filter(Customer.id == vehicle.owner_id).first()
        owner_name = owner.name if owner else None
    return _to_response(vehicle, owner_name)


@router.post("/", response_model=VehicleResponse, summary="新增车辆")
def create_vehicle(
    data: VehicleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_writer(current_user)
    plate = _norm_plate(data.plate)
    vin = _norm_vin(data.vin)
    if is_owner(current_user):
        data.owner_id = ensure_customer_for_user(db, current_user).id
    _ensure_owner(db, data.owner_id)
    if db.query(Vehicle.id).filter(Vehicle.plate == plate).first():
        raise HTTPException(status_code=400, detail="车牌号已存在")
    if vin and db.query(Vehicle.id).filter(Vehicle.vin == vin).first():
        raise HTTPException(status_code=400, detail="VIN 已存在")
    payload = data.model_dump()
    payload["plate"] = plate
    payload["vin"] = vin
    vehicle = Vehicle(**payload)
    db.add(vehicle)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="车辆保存失败，车牌或 VIN 冲突")
    db.refresh(vehicle)
    return get_vehicle(vehicle.id, db, current_user)


@router.put("/{vehicle_id}", response_model=VehicleResponse, summary="更新车辆")
def update_vehicle(
    vehicle_id: int,
    data: VehicleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_writer(current_user)
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="车辆不存在")
    if is_owner(current_user):
        ids = set(customer_ids_for_user(db, current_user))
        if vehicle.owner_id not in ids:
            raise HTTPException(status_code=404, detail="车辆不存在")
    changes = data.model_dump(exclude_unset=True)
    if is_owner(current_user):
        changes.pop("owner_id", None)
    if "plate" in changes:
        plate = _norm_plate(changes["plate"])
        exists = db.query(Vehicle.id).filter(Vehicle.plate == plate, Vehicle.id != vehicle_id).first()
        if exists:
            raise HTTPException(status_code=400, detail="车牌号已存在")
        changes["plate"] = plate
    if "vin" in changes:
        vin = _norm_vin(changes["vin"])
        if vin:
            exists = db.query(Vehicle.id).filter(Vehicle.vin == vin, Vehicle.id != vehicle_id).first()
            if exists:
                raise HTTPException(status_code=400, detail="VIN 已存在")
        changes["vin"] = vin
    if "owner_id" in changes:
        _ensure_owner(db, changes["owner_id"])
    for key, val in changes.items():
        setattr(vehicle, key, val)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="车辆保存失败，车牌或 VIN 冲突")
    db.refresh(vehicle)
    return get_vehicle(vehicle.id, db, current_user)


@router.delete("/{vehicle_id}", summary="删除车辆")
def delete_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_writer(current_user)
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="车辆不存在")
    if is_owner(current_user):
        raise HTTPException(status_code=403, detail="车主不能删除车辆档案，请联系门店")
    db.delete(vehicle)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="车辆已被工单或预约引用，无法删除")
    return {"message": "车辆已删除"}
