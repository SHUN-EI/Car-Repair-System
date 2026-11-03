"""第三方 MCP 的只读清单和鉴权判断。

默认不注册写工具。公开入口只挂下面这几项只读工具。
鉴权接受 MCP_API_KEY，或现有登录 JWT（没有 scope 时视为 mcp:read；
写了 scope 则必须包含 mcp:read）。
"""
from __future__ import annotations

from typing import Optional

PUBLIC_READ_TOOLS = (
    "query_work_order",
    "query_compatible_parts",
    "recommend_service",
    "query_inventory",
    "get_workorder_stats",
)

# 会改数据或写入会话的工具。HTTP 默认不挂。
WRITE_TOOLS = (
    "draft_quote",
    "guided_repair_chat",
)

READ_SCOPE = "mcp:read"


def is_public_read_tool(name: str) -> bool:
    return name in PUBLIC_READ_TOOLS


def write_tools_enabled(flag: bool) -> tuple:
    """返回当前 HTTP 允许挂出的写工具名。默认空。"""
    if not flag:
        return ()
    return WRITE_TOOLS


def _scopes_of(payload: Optional[dict]) -> Optional[set]:
    if not payload or "scope" not in payload or payload.get("scope") is None:
        return None
    raw = payload.get("scope")
    if isinstance(raw, str):
        return {item for item in raw.replace(",", " ").split() if item}
    if isinstance(raw, (list, tuple, set)):
        return {str(item) for item in raw if item}
    return set()


def token_has_read_scope(payload: Optional[dict]) -> bool:
    """没有 scope 的登录令牌按只读放行；显式 scope 必须带 mcp:read。"""
    if not payload:
        return False
    scopes = _scopes_of(payload)
    if scopes is None:
        return True
    return READ_SCOPE in scopes


def decide_mcp_access(
    *,
    path: str,
    authorization: str = "",
    api_key: str = "",
    token_payload: Optional[dict] = None,
    client_host: str = "",
    localhost_hosts: Optional[set] = None,
    public_enabled: bool = True,
) -> Optional[tuple]:
    """返回 None 表示放行，否则 (status_code, detail)。非 MCP 路径直接放行。"""
    if not path.startswith("/mcp"):
        return None
    hosts = localhost_hosts or {"127.0.0.1", "::1", "localhost"}
    is_public = path.startswith("/mcp/public")
    if is_public and not public_enabled:
        return (404, "MCP 公开入口未启用")

    bearer = ""
    if authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    key_ok = bool(api_key) and bearer == api_key
    jwt_ok = token_has_read_scope(token_payload)

    if is_public:
        if key_ok or jwt_ok:
            return None
        return (401, "公开 MCP 需要 API Key 或登录令牌")

    if api_key:
        if key_ok or jwt_ok:
            return None
        return (403, "Forbidden: invalid MCP API key")
    if client_host in hosts:
        return None
    return (403, "Forbidden: MCP only accessible from localhost")
