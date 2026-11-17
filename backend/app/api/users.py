"""用户管理接口：分页查询、创建、更新、删除，以及角色和门店绑定的权限控制。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from passlib.context import CryptContext
from loguru import logger
from app.core.database import get_db
from app.core.security import get_current_user
from app.core.cache_service import cache_service
from app.domain.store_scope import role_name
from app.models.user import User, UserRole
from app.schemas import UserCreate, UserUpdate, UserResponse, PaginatedResponse

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _u_to_dict(u: User) -> dict:
    """把用户转成接口字典，故意去掉 password_hash，避免把密码哈希返回给前端。"""
    return {c.name: getattr(u, c.name) for c in u.__table__.columns if c.name != 'password_hash'}


def _require_admin(user: User) -> None:
    """校验当前用户是管理员，否则返回 403。"""
    if role_name(user) != "ADMIN":
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")


def _require_store_binder(user: User) -> None:
    """校验当前用户是管理员或主管，否则不能给账号绑定门店。"""
    if role_name(user) not in ("ADMIN", "SUPERVISOR"):
        raise HTTPException(status_code=403, detail="仅管理员或主管可绑定门店")


@router.get("/me", summary="获取当前登录用户信息")
def get_current_user_me(current_user: User = Depends(get_current_user)):
    """返回当前登录用户的完整信息（含钉钉绑定状态）"""
    return _u_to_dict(current_user)


@router.get("/", response_model=PaginatedResponse[UserResponse], summary="获取用户列表")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=1000),
    role: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分页列出用户，可按角色、用户名或真实姓名过滤。当前实现仅要求登录，返回中不含密码哈希。"""
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    if keyword:
        query = query.filter(
            User.username.ilike(f"%{keyword}%") |
            User.real_name.ilike(f"%{keyword}%")
        )
    total = query.count()
    items = query.order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [_u_to_dict(u) for u in items], "page": page, "page_size": page_size}


@router.get("/{user_id}", response_model=UserResponse, summary="获取用户详情（带缓存）")
def get_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """按 ID 获取用户资料，结果缓存 5 分钟。用户不存在返回 404。"""
    cache_key = f"user:{user_id}"
    cached = cache_service.get(cache_key)
    if cached:
        return cached

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    result = _u_to_dict(user)
    cache_service.set(cache_key, result, ttl=300)
    return result


@router.post("/", response_model=UserResponse, summary="创建用户")
def create_user(data: UserCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """管理员创建用户。用户名不能重复；明文密码会在入库前哈希，不会以明文保存。"""
    _require_admin(current_user)
    existing = db.query(User).filter(User.username == data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")
    data_dict = data.model_dump()
    data_dict["password_hash"] = pwd_context.hash(data_dict.pop("password"))
    user = User(**data_dict)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/{user_id}", response_model=UserResponse, summary="更新用户")
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新用户资料。只有管理员能改角色；管理员或主管才能绑定门店，且主管只能绑到自己的门店。普通用户只能改自己的资料，且不能改角色、门店和启用状态。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    changes = data.model_dump(exclude_unset=True)
    actor = role_name(current_user)
    if "role" in changes and actor != "ADMIN":
        raise HTTPException(status_code=403, detail="仅管理员可修改角色")
    if "store_id" in changes:
        _require_store_binder(current_user)
        if actor == "SUPERVISOR" and current_user.store_id and changes["store_id"] not in (None, current_user.store_id):
            raise HTTPException(status_code=403, detail="主管只能把账号绑定到自己的门店")
    if actor not in ("ADMIN", "SUPERVISOR") and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="只能修改自己的资料")
    if actor not in ("ADMIN", "SUPERVISOR"):
        for locked in ("role", "store_id", "is_active"):
            changes.pop(locked, None)
    for key, val in changes.items():
        setattr(user, key, val)
    db.commit()
    db.refresh(user)
    cache_service.delete(f"user:{user_id}")
    return user


@router.delete("/{user_id}", summary="删除用户")
def delete_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """管理员删除用户，同时清掉该用户的缓存。用户不存在返回 404。"""
    _require_admin(current_user)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.delete(user)
    db.commit()
    cache_service.delete(f"user:{user_id}")
    return {"message": "用户已删除"}


@router.post("/{user_id}/dingtalk/unbind", summary="管理员代解绑钉钉")
def admin_unbind_dingtalk(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """管理员代员工解绑钉钉账号（应对员工离职场景）"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="仅管理员可代解绑")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not user.dingtalk_userid:
        raise HTTPException(status_code=400, detail="该用户未绑定钉钉")

    user.dingtalk_userid = None
    user.dingtalk_bound_at = None
    db.commit()
    cache_service.delete(f"user:{user_id}")
    logger.info(f"[User] 管理员代解绑钉钉: target_user={user_id}, admin={current_user.id}")
    return {"message": f"已解绑用户「{user.real_name}」的钉钉账号"}