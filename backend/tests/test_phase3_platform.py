"""Phase 3：门店隔离、回访提醒、采购入库、只读 MCP。不连数据库。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.follow_ups import router as follow_router  # noqa: E402
from app.api.purchase_orders import router as po_router  # noqa: E402
from app.domain.follow_up import (  # noqa: E402
    DEFAULT_DELAY_DAYS,
    follow_up_message,
    reminder_delivered,
    status_label_for,
)
from app.domain.procurement import next_po_no, po_status_after_receive, receive_qty  # noqa: E402
from app.domain.store_scope import (  # noqa: E402
    StoreScopeError,
    ensure_writable_store,
    resolve_store_scope,
    row_in_scope,
)
from app.mcp.access import (  # noqa: E402
    PUBLIC_READ_TOOLS,
    WRITE_TOOLS,
    decide_mcp_access,
    is_public_read_tool,
    write_tools_enabled,
)
from app.core.config import settings  # noqa: E402


class _User:
    def __init__(self, role, store_id=None):
        self.role = role
        self.store_id = store_id


class TestStoreScope:
    def test_admin_sees_all_unless_a_store_is_requested(self):
        admin = _User("ADMIN")
        assert resolve_store_scope(admin).mode == "all"
        picked = resolve_store_scope(admin, 2)
        assert picked.mode == "store" and picked.store_id == 2
        assert row_in_scope(picked, 2)
        assert not row_in_scope(picked, 3)

    def test_store_role_is_locked_to_the_bound_store(self):
        tech = _User("TECHNICIAN", store_id=5)
        scope = resolve_store_scope(tech, requested_store_id=9)
        assert scope.store_id == 5
        assert row_in_scope(scope, 5)
        assert not row_in_scope(scope, None)
        assert not row_in_scope(scope, 9)
        assert ensure_writable_store(tech, None) == 5
        try:
            ensure_writable_store(tech, 9)
        except StoreScopeError as exc:
            assert "本门店" in exc.message
        else:
            raise AssertionError("店内角色不能写到别的门店")

    def test_unbound_store_role_only_sees_legacy_rows(self):
        tech = _User("SUPERVISOR", store_id=None)
        scope = resolve_store_scope(tech)
        assert scope.mode == "legacy"
        assert row_in_scope(scope, None)
        assert not row_in_scope(scope, 1)
        try:
            ensure_writable_store(tech, 1)
        except StoreScopeError as exc:
            assert "未绑定" in exc.message
        else:
            raise AssertionError("未绑定门店不能写入已分店数据")


class TestFollowUp:
    def test_messages_are_revisit_or_rating_not_a_score(self):
        revisit = follow_up_message("REVISIT", "WO-1", "沪A12345")
        rating = follow_up_message("RATING", "WO-1", "")
        assert "回访" in revisit and "沪A12345" in revisit
        assert "评价" in rating
        assert "回复率" not in revisit
        assert status_label_for("REVISIT") == "邀请回访"
        assert DEFAULT_DELAY_DAYS["RATING"] == 1
        assert DEFAULT_DELAY_DAYS["REVISIT"] == 7

    def test_mock_channel_counts_as_delivered_and_skip_does_not(self):
        assert reminder_delivered({"sms": "mock", "dingtalk": "skipped", "inbox": "skipped"})
        assert reminder_delivered({"sms": "sent", "dingtalk": "skipped", "inbox": "skipped"})
        assert not reminder_delivered({"sms": "skipped", "dingtalk": "skipped", "inbox": "skipped", "reason": "无客户"})
        assert not reminder_delivered({"sms": "failed", "dingtalk": "failed", "inbox": "skipped"})


class TestPurchase:
    def test_receive_status_and_quantity(self):
        assert po_status_after_receive([(10, 0), (5, 0)]) == "ORDERED"
        assert po_status_after_receive([(10, 4), (5, 0)]) == "PARTIAL"
        assert po_status_after_receive([(10, 10), (5, 5)]) == "RECEIVED"
        assert receive_qty(10, 4, None) == 6
        assert receive_qty(10, 10, None) == 0
        try:
            receive_qty(10, 4, 9)
        except ValueError as exc:
            assert "未收" in str(exc)
        else:
            raise AssertionError("不能超收")

    def test_po_number_increments_same_day(self):
        assert next_po_no(["PO-20261103-002", "QT-1"], "20261103") == "PO-20261103-003"
        assert next_po_no([], "20261103") == "PO-20261103-001"


class TestMcpAccess:
    def test_public_set_is_read_only(self):
        assert "draft_quote" not in PUBLIC_READ_TOOLS
        assert "guided_repair_chat" not in PUBLIC_READ_TOOLS
        assert is_public_read_tool("query_work_order")
        assert is_public_read_tool("query_compatible_parts")
        assert not settings.MCP_ENABLE_WRITE_TOOLS
        assert write_tools_enabled(False) == ()
        assert "draft_quote" in write_tools_enabled(True)

    def test_public_entry_requires_key_or_login_token(self):
        denied = decide_mcp_access(path="/mcp/public", authorization="", api_key="secret", client_host="10.0.0.8")
        assert denied[0] == 401
        assert decide_mcp_access(
            path="/mcp/public", authorization="Bearer secret", api_key="secret", client_host="10.0.0.8",
        ) is None
        assert decide_mcp_access(
            path="/mcp/public",
            authorization="Bearer login-token",
            api_key="secret",
            token_payload={"sub": "1"},
            client_host="10.0.0.8",
        ) is None
        scoped = decide_mcp_access(
            path="/mcp/public",
            authorization="Bearer login-token",
            api_key="",
            token_payload={"sub": "1", "scope": "other"},
            client_host="10.0.0.8",
        )
        assert scoped[0] == 401

    def test_internal_mcp_stays_local_when_no_key(self):
        assert decide_mcp_access(path="/mcp", client_host="127.0.0.1", api_key="") is None
        blocked = decide_mcp_access(path="/mcp", client_host="10.0.0.8", api_key="")
        assert blocked[0] == 403

    def test_routes_and_source_keep_write_tools_off_by_default(self):
        follow_paths = {route.path for route in follow_router.routes}
        assert "/dispatch" in follow_paths
        assert "/{reminder_id}/cancel" in follow_paths
        po_paths = {route.path for route in po_router.routes}
        assert "/{order_id}/receive" in po_paths
        assert "/{order_id}/cancel" in po_paths
        root = Path(__file__).resolve().parents[1]
        server = (root / "app" / "mcp" / "server.py").read_text(encoding="utf-8")
        public = (root / "app" / "mcp" / "public.py").read_text(encoding="utf-8")
        main = (root / "app" / "main.py").read_text(encoding="utf-8")
        assert "async def draft_quote" in server
        assert "MCP_ENABLE_WRITE_TOOLS" in server
        assert "draft_quote" not in public
        for name in PUBLIC_READ_TOOLS:
            assert name in public
        for name in WRITE_TOOLS:
            assert f"async def {name}" not in public or name == "never"
        assert "/mcp/public" in main
        assert "follow-ups" in main
        assert "purchase-orders" in main
