"""门店数据范围。

管理员不带门店条件时看全部，带上门店条件时只看该店。
店内角色（主管 / 维修员 / 操作工）只要用户上写了 store_id，就锁定在这一家，
请求里的门店参数不能把范围改到别的店。
还没绑定门店的店内角色只看 store_id 为空的历史数据。
车主不走这里，仍按客户档案过滤。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


STORE_ROLES = frozenset({"SUPERVISOR", "TECHNICIAN", "WORKER"})


class StoreScopeError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def role_name(user) -> str:
    role = getattr(user, "role", "") or ""
    return role.value if hasattr(role, "value") else str(role)


def is_admin(user) -> bool:
    return role_name(user) == "ADMIN"


def is_store_role(user) -> bool:
    return role_name(user) in STORE_ROLES


@dataclass(frozen=True)
class StoreScope:
    """mode: all 不过滤；store 锁定一家；legacy 只看未分店的历史行。"""

    mode: str
    store_id: Optional[int] = None


def resolve_store_scope(user, requested_store_id: Optional[int] = None) -> StoreScope:
    if is_admin(user):
        if requested_store_id:
            return StoreScope("store", int(requested_store_id))
        return StoreScope("all")
    if is_store_role(user):
        bound = getattr(user, "store_id", None)
        if bound:
            return StoreScope("store", int(bound))
        return StoreScope("legacy")
    return StoreScope("all")


def row_in_scope(scope: StoreScope, row_store_id: Optional[int]) -> bool:
    if scope.mode == "all":
        return True
    if scope.mode == "legacy":
        return row_store_id is None
    return row_store_id is not None and int(row_store_id) == int(scope.store_id)


def apply_store_column(query, column, scope: StoreScope):
    if scope.mode == "store":
        return query.filter(column == scope.store_id)
    if scope.mode == "legacy":
        return query.filter(column.is_(None))
    return query


def ensure_writable_store(user, store_id: Optional[int]) -> Optional[int]:
    """写入时决定落在哪家店。店内角色不能写到别的店。"""
    scope = resolve_store_scope(user)
    if scope.mode == "store":
        if store_id is not None and int(store_id) != int(scope.store_id):
            raise StoreScopeError("只能操作本门店数据")
        return int(scope.store_id)
    if scope.mode == "legacy":
        if store_id is not None:
            raise StoreScopeError("当前账号未绑定门店，不能写入已分店的数据")
        return None
    return store_id
