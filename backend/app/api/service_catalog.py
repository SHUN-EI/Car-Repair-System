"""保养套餐和项目。主管只读，推荐接口所有登录用户可查。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import Optional

from app.agents.service_tools import recommend_service_packages
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.service_catalog import ServicePackage, ServiceSku
from app.models.user import User
from app.schemas import (
    PaginatedResponse,
    ServicePackageCreate, ServicePackageResponse, ServicePackageUpdate,
    ServiceRecommendRequest,
    ServiceSkuCreate, ServiceSkuResponse, ServiceSkuUpdate,
)

packages_router = APIRouter()
skus_router = APIRouter()


def _role(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role or "")


def _ensure_writer(user: User):
    if _role(user) == "SUPERVISOR":
        raise HTTPException(status_code=403, detail="主管仅可查看，如需修改请联系管理员")
    if _role(user) == "OWNER":
        raise HTTPException(status_code=403, detail="车主不能维护保养目录")


def _keywords(value):
    if value is None:
        return None
    cleaned = []
    for item in value:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text[:40])
    return cleaned or None


def _check_mileage(start, end):
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="里程下限不能大于上限")


def _commit(db: Session, conflict: str):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail=conflict)


def _page(query, page: int, page_size: int):
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return total, items


@packages_router.get("/", response_model=PaginatedResponse[ServicePackageResponse], summary="保养套餐列表")
def list_packages(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: Optional[str] = None,
    brand: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ServicePackage)
    if brand:
        query = query.filter(ServicePackage.brand == brand)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(ServicePackage.code.ilike(like) | ServicePackage.name.ilike(like))
    total, items = _page(query.order_by(ServicePackage.id.desc()), page, page_size)
    return {"total": total, "items": items, "page": page, "page_size": page_size}


@packages_router.post("/recommend", summary="按车型、里程、症状推荐保养套餐")
def recommend_packages(
    data: ServiceRecommendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return recommend_service_packages(
        db,
        vehicle_id=data.vehicle_id,
        plate=data.plate,
        brand=data.brand,
        series=data.series,
        mileage=data.mileage,
        symptoms=data.symptoms,
    )


@packages_router.get("/{package_id}", response_model=ServicePackageResponse, summary="保养套餐详情")
def get_package(package_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = db.query(ServicePackage).filter(ServicePackage.id == package_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="保养套餐不存在")
    return row


@packages_router.post("/", response_model=ServicePackageResponse, summary="新增保养套餐")
def create_package(data: ServicePackageCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    _check_mileage(data.mileage_from, data.mileage_to)
    code = data.code.strip()
    if db.query(ServicePackage.id).filter(ServicePackage.code == code).first():
        raise HTTPException(status_code=400, detail="套餐编码已存在")
    payload = data.model_dump()
    payload["code"] = code
    payload["symptom_keywords"] = _keywords(payload.get("symptom_keywords"))
    row = ServicePackage(**payload)
    db.add(row)
    _commit(db, "套餐编码已存在")
    db.refresh(row)
    return row


@packages_router.put("/{package_id}", response_model=ServicePackageResponse, summary="更新保养套餐")
def update_package(
    package_id: int,
    data: ServicePackageUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_writer(current_user)
    row = db.query(ServicePackage).filter(ServicePackage.id == package_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="保养套餐不存在")
    changes = data.model_dump(exclude_unset=True)
    if "symptom_keywords" in changes:
        changes["symptom_keywords"] = _keywords(changes["symptom_keywords"])
    for key, val in changes.items():
        setattr(row, key, val)
    _check_mileage(row.mileage_from, row.mileage_to)
    _commit(db, "保养套餐保存失败")
    db.refresh(row)
    return row


@packages_router.delete("/{package_id}", summary="删除保养套餐")
def delete_package(package_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    row = db.query(ServicePackage).filter(ServicePackage.id == package_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="保养套餐不存在")
    db.delete(row)
    _commit(db, "保养套餐删除失败")
    return {"message": "保养套餐已删除"}


@skus_router.get("/", response_model=PaginatedResponse[ServiceSkuResponse], summary="服务项目列表")
def list_skus(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: Optional[str] = None,
    package_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ServiceSku)
    if package_id:
        query = query.filter(ServiceSku.package_id == package_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(ServiceSku.code.ilike(like) | ServiceSku.name.ilike(like))
    total, items = _page(query.order_by(ServiceSku.id.desc()), page, page_size)
    return {"total": total, "items": items, "page": page, "page_size": page_size}


@skus_router.get("/{sku_id}", response_model=ServiceSkuResponse, summary="服务项目详情")
def get_sku(sku_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = db.query(ServiceSku).filter(ServiceSku.id == sku_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="服务项目不存在")
    return row


@skus_router.post("/", response_model=ServiceSkuResponse, summary="新增服务项目")
def create_sku(data: ServiceSkuCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    _check_mileage(data.mileage_from, data.mileage_to)
    if data.package_id and not db.query(ServicePackage.id).filter(ServicePackage.id == data.package_id).first():
        raise HTTPException(status_code=400, detail="所属套餐不存在")
    code = data.code.strip()
    if db.query(ServiceSku.id).filter(ServiceSku.code == code).first():
        raise HTTPException(status_code=400, detail="项目编码已存在")
    payload = data.model_dump()
    payload["code"] = code
    payload["symptom_keywords"] = _keywords(payload.get("symptom_keywords"))
    row = ServiceSku(**payload)
    db.add(row)
    _commit(db, "项目编码已存在")
    db.refresh(row)
    return row


@skus_router.put("/{sku_id}", response_model=ServiceSkuResponse, summary="更新服务项目")
def update_sku(
    sku_id: int,
    data: ServiceSkuUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_writer(current_user)
    row = db.query(ServiceSku).filter(ServiceSku.id == sku_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="服务项目不存在")
    changes = data.model_dump(exclude_unset=True)
    if "package_id" in changes and changes["package_id"]:
        if not db.query(ServicePackage.id).filter(ServicePackage.id == changes["package_id"]).first():
            raise HTTPException(status_code=400, detail="所属套餐不存在")
    if "symptom_keywords" in changes:
        changes["symptom_keywords"] = _keywords(changes["symptom_keywords"])
    for key, val in changes.items():
        setattr(row, key, val)
    _check_mileage(row.mileage_from, row.mileage_to)
    _commit(db, "服务项目保存失败")
    db.refresh(row)
    return row


@skus_router.delete("/{sku_id}", summary="删除服务项目")
def delete_sku(sku_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ensure_writer(current_user)
    row = db.query(ServiceSku).filter(ServiceSku.id == sku_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="服务项目不存在")
    db.delete(row)
    _commit(db, "服务项目删除失败")
    return {"message": "服务项目已删除"}
