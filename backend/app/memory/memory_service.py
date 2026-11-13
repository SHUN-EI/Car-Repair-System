"""Agent 记忆门面：统一短期会话 Redis 读写与会话摘要入口。

三层映射（按现网技术栈，不是契约里的 MySQL）：
- 工作记忆：请求期内 scratchpad / 中间态，不落盘、不新做持久化。
- 短期会话：Redis（经 cache_service，自动加前缀 maint:），key 与 TTL 与下沉前完全一致。
- 长期事实：PostgreSQL。现网没有独立的「长期记忆事实表」，本模块不新造表，
  也不把工单/库存/报价等业务持久化收进记忆层。会话摘要只做计算，结果写回短期会话 payload。

调用方不要自行拼接 session key 或传入 TTL。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.cache_service import cache_service

# ---- 逻辑 key（cache_service 会再加 maint: 前缀，实际 Redis key 见各常量注释）----
GUIDED_REPAIR_SESSION_PREFIX = "guided_repair_session:"
EXPERT_REPAIR_SESSION_PREFIX = "expert_repair_session:"
MCP_STAFF_GUIDED_SESSION_PREFIX = "mcp/staff_guid:session:"
MCP_STAFF_GUIDED_LAST_PREFIX = "mcp/staff_guid:last:"

# 与下沉前各调用点字面量一致：24 小时
GUIDED_REPAIR_SESSION_TTL = 24 * 3600
EXPERT_REPAIR_SESSION_TTL = 24 * 3600
MCP_STAFF_GUIDED_SESSION_TTL = 24 * 3600

# MCP 模块历史对外名，保持可导入
GUIDED_SESSION_TTL = MCP_STAFF_GUIDED_SESSION_TTL


class MemoryService:
    """记忆门面。短期会话委托 cache_service；摘要委托 SessionSummarizer。"""

    # ---------- 工作记忆（不持久化） ----------
    def new_scratchpad(self) -> List[dict]:
        """请求期内工作记忆容器，不写入 Redis / PostgreSQL。"""
        return []

    # ---------- 短期会话：追踪维修 ----------
    def get_guided_repair_session(self, session_id: str) -> Optional[Any]:
        return cache_service.get(f"{GUIDED_REPAIR_SESSION_PREFIX}{session_id}")

    def set_guided_repair_session(self, session_id: str, data: Any) -> bool:
        return cache_service.set(
            f"{GUIDED_REPAIR_SESSION_PREFIX}{session_id}",
            data,
            ttl=GUIDED_REPAIR_SESSION_TTL,
        )

    # ---------- 短期会话：专家模式 ----------
    def get_expert_repair_session(self, session_id: str) -> Optional[Any]:
        return cache_service.get(f"{EXPERT_REPAIR_SESSION_PREFIX}{session_id}")

    def set_expert_repair_session(self, session_id: str, data: Any) -> bool:
        return cache_service.set(
            f"{EXPERT_REPAIR_SESSION_PREFIX}{session_id}",
            data,
            ttl=EXPERT_REPAIR_SESSION_TTL,
        )

    # ---------- 短期会话：MCP 员工 ↔ 追踪维修会话映射 ----------
    def get_mcp_staff_guided_session(self, staff_id: str) -> Optional[Any]:
        return cache_service.get(f"{MCP_STAFF_GUIDED_SESSION_PREFIX}{staff_id}")

    def set_mcp_staff_guided_session(self, staff_id: str, session_id: Any) -> bool:
        return cache_service.set(
            f"{MCP_STAFF_GUIDED_SESSION_PREFIX}{staff_id}",
            session_id,
            ttl=MCP_STAFF_GUIDED_SESSION_TTL,
        )

    def get_mcp_staff_guided_last(self, staff_id: str) -> Optional[Any]:
        return cache_service.get(f"{MCP_STAFF_GUIDED_LAST_PREFIX}{staff_id}")

    def set_mcp_staff_guided_last(self, staff_id: str, timestamp: Any) -> bool:
        return cache_service.set(
            f"{MCP_STAFF_GUIDED_LAST_PREFIX}{staff_id}",
            timestamp,
            ttl=MCP_STAFF_GUIDED_SESSION_TTL,
        )

    # ---------- 会话摘要（计算，不单独落长期表） ----------
    def summarize(self, messages: List[dict]) -> str:
        """压缩对话历史为结构化摘要；实现仍是 SessionSummarizer，不写独立表。"""
        from app.agents.session_summarizer import session_summarizer
        return session_summarizer.summarize(messages)


memory_service = MemoryService()
