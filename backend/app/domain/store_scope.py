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
    """解析或应用门店数据范围失败时抛出的业务异常，接口层通常转成 403。"""
    def __init__(self, message: str):
        """保存可读的错误说明，供接口层放到 HTTP 响应里。"""
        super().__init__(message)
        self.message = message


def role_name(user) -> str:
    """取出用户角色的字符串名。兼容枚举（用 .value）和普通字符串两种存法，缺省时视为空串。"""
    role = getattr(user, "role", "") or ""
    return role.value if hasattr(role, "value") else str(role)


def is_admin(user) -> bool:
    """判断用户是否为管理员 ADMIN，管理员默认可看全部门店数据。"""
    return role_name(user) == "ADMIN"


def is_store_role(user) -> bool:
    """判断用户是否属于绑定门店的岗位（STORE_ROLES，如主管、技师、车间工人），这类角色默认只能看本店数据。"""
    return role_name(user) in STORE_ROLES


@dataclass(frozen=True)
class StoreScope:
    """mode: all 不过滤；store 锁定一家；legacy 只看未分店的历史行。"""

    mode: str
    store_id: Optional[int] = None


def resolve_store_scope(user, requested_store_id: Optional[int] = None) -> StoreScope:
    """根据角色和请求里的门店参数，得到本次查询应使用的数据范围。

    管理员不带门店参数时是 all（全部门店），带参数则锁定到该店；门店角色优先用账号绑定的 store_id，没有绑定门店时退回 legacy（只看 store_id 为空的历史数据）。其它角色（含车主）当前也返回 all，调用方若需按客户档案收窄，要另外使用 owner_access。
    """
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
    """判断一行记录的 store_id 是否落在给定范围内。all 全部通过；legacy 只接受 store_id 为空的行；store 模式必须等于范围内的门店 ID。"""
    if scope.mode == "all":
        return True
    if scope.mode == "legacy":
        return row_store_id is None
    return row_store_id is not None and int(row_store_id) == int(scope.store_id)


def apply_store_column(query, column, scope: StoreScope):
    """把门店范围落到 SQLAlchemy 查询上：store 模式过滤为指定门店，legacy 过滤 store_id 为空，all 不加条件。"""
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
