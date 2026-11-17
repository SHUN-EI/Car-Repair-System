"""Phase 1：汽修闭环、预约时段、领料门槛、问诊文案、样例语料。不连数据库。"""
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.answer_generator import AnswerGenerator  # noqa: E402
from app.agents.guided_repair_agent import GuidedRepairAgent  # noqa: E402
from app.agents.retrieval_flow import repair_intent_fast_check  # noqa: E402
from app.core.dingtalk_wo_card import ACTION_MAP, ACTION_QC  # noqa: E402
from app.domain.appointment_slots import build_slot_grid, is_bookable_slot  # noqa: E402
from app.domain.auto_repair_seed import KNOWLEDGE_SEEDS, MANUAL_CODE_SEEDS  # noqa: E402
from app.domain.work_order_status import (  # noqa: E402
    is_allowed_transition,
    is_auto_repair_lane,
    next_auto_step,
    parts_issue_allowed,
)
from app.api.work_orders import router as work_orders_router  # noqa: E402
from app.api.dispatch import router as dispatch_router  # noqa: E402
from app.api.spare_parts import router as spare_router  # noqa: E402
from app.api.service_domain import appointments_router  # noqa: E402


class TestAutoRepairLoop:
    """汽修闭环：预约、到店、取消以及与工业单的区分。"""
    def test_store_path_and_cancel(self):
        """门店路径上的预约可以取消。"""
        assert next_auto_step("DRAFT") == "INTAKE"
        cursor = "INTAKE"
        seen = [cursor]
        while True:
            nxt = next_auto_step(cursor)
            if not nxt:
                break
            assert is_allowed_transition(cursor, nxt)
            seen.append(nxt)
            cursor = nxt
        assert seen == [
            "INTAKE", "DIAGNOSING", "QUOTING", "APPROVED",
            "IN_PROGRESS", "QC", "COMPLETED", "CLOSED",
        ]
        assert is_allowed_transition("QUOTING", "CANCELLED")
        assert not is_allowed_transition("CLOSED", "INTAKE")
        # 工业车道的完成维修仍然可以去待归档
        assert is_allowed_transition("IN_PROGRESS", "ARCHIVING")

    def test_lane_detection_does_not_swallow_industrial_jobs(self):
        """车道识别不应把工业工单误判成汽修单。"""
        assert is_auto_repair_lane(vehicle_id=3)
        assert is_auto_repair_lane(status="INTAKE")
        assert not is_auto_repair_lane(status="IN_PROGRESS")
        assert not is_auto_repair_lane(status="ASSIGNED")

    def test_parts_only_while_in_service(self):
        """只有在维修过程中才允许按工单扣料。"""
        assert parts_issue_allowed("IN_PROGRESS")
        assert parts_issue_allowed("QC")
        assert parts_issue_allowed("INSPECTING")
        assert not parts_issue_allowed("CLOSED")
        assert not parts_issue_allowed("COMPLETED")
        assert not parts_issue_allowed("DRAFT")


class TestSlots:
    """预约时段格子的计算。"""
    def test_grid_marks_busy_bay(self):
        """已被占用的工位时段应在格子上标为忙碌。"""
        day = datetime(2026, 11, 3)
        busy = {(2, datetime(2026, 11, 3, 9, 0, 0))}
        rows = build_slot_grid(
            day.date(),
            [{"id": 1, "name": "机电1", "code": "B1"}, {"id": 2, "name": "机电2", "code": "B2"}],
            busy,
        )
        assert len(rows) == 9 * 2
        taken = [row for row in rows if row["bay_id"] == 2 and row["start"].endswith("09:00:00")]
        assert taken and taken[0]["available"] is False
        free = [row for row in rows if row["bay_id"] == 1 and row["start"].endswith("09:00:00")]
        assert free[0]["available"] is True

    def test_bookable_hours(self):
        """只有营业时间内的整点可以预约。"""
        assert is_bookable_slot(datetime(2026, 11, 3, 9, 0, 0))
        assert is_bookable_slot(datetime(2026, 11, 3, 17, 0, 0))
        assert not is_bookable_slot(datetime(2026, 11, 3, 8, 0, 0))
        assert not is_bookable_slot(datetime(2026, 11, 3, 18, 0, 0))
        assert not is_bookable_slot(datetime(2026, 11, 3, 9, 30, 0))


class TestConsultCopy:
    """问诊文案和提示词规则。"""
    def test_prompts_keep_retrieval_rules_and_add_booking(self):
        """问诊提示词在保留检索规则的同时，应引导预约。"""
        assert "建议项目" in AnswerGenerator.CONSULT_SYSTEM_PROMPT
        assert "是否预约" in AnswerGenerator.CONSULT_SYSTEM_PROMPT
        assert "症状理解" in AnswerGenerator.CONSULT_SYSTEM_PROMPT
        assert "设备维修知识库检索助手" in AnswerGenerator.SYSTEM_PROMPT
        assert "是否预约" in GuidedRepairAgent.CONSULT_CHAT_SYSTEM_PROMPT
        assert "【分析】" in GuidedRepairAgent.CHAT_SYSTEM_PROMPT

    def test_empty_consult_suggests_store_without_inventing_items(self):
        """没有检索结果时只建议到店，不能虚构项目。"""
        chunks = "".join(AnswerGenerator().stream_answer("刹车有异响", [], scene="consult"))
        assert "建议预约到店" in chunks
        assert "具体项目" in chunks
        plain = "".join(AnswerGenerator().stream_answer("刹车有异响", []))
        assert "历史案例" in plain
        assert "建议预约到店" not in plain

    def test_auto_keywords_pass_the_existing_gate(self):
        """汽修相关关键词应能通过现有的问诊入口判断。"""
        assert repair_intent_fast_check("该做保养吗")["decision"] == "related"
        assert repair_intent_fast_check("你好")["decision"] == "irrelevant"


class TestSeedAndRoutes:
    """样例数据和 Phase 1 路由是否到位。"""
    def test_seed_is_a_small_real_set(self):
        """种子数据应是一小份真实可用的样例，而不是空壳。"""
        assert len(KNOWLEDGE_SEEDS) >= 6
        assert len(MANUAL_CODE_SEEDS) >= 2
        titles = [row["title"] for row in KNOWLEDGE_SEEDS]
        assert len(titles) == len(set(titles))
        assert any("保养" in row["title"] or "保养规范" in row["fault_tags"] for row in KNOWLEDGE_SEEDS)
        codes = [row["error_code"] for row in MANUAL_CODE_SEEDS]
        assert "P0300" in codes

    def test_phase1_routes_exist(self):
        """Phase 1 相关路由已经挂到应用上。"""
        wo_paths = {route.path for route in work_orders_router.routes}
        assert "/from-appointment" in wo_paths
        assert "/{work_order_id}/transition" in wo_paths
        dispatch_paths = {route.path for route in dispatch_router.routes}
        assert "/api/v1/dispatch/bind" in dispatch_paths
        spare_paths = {route.path for route in spare_router.routes}
        assert "/issue" in spare_paths
        appointment_paths = {route.path for route in appointments_router.routes}
        assert "/slots" in appointment_paths
        assert "/book" in appointment_paths

    def test_dingtalk_reuses_transition_for_qc(self):
        """钉钉完成汽修单时应复用状态机走到质检，而不是另写一套。"""
        assert ACTION_MAP[ACTION_QC][0] == "QC"
