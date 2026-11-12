"""双 Agent 精简：路由与门面单元测试。不连数据库、不调用 LLM。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.router import (
    CONSULT,
    WORK_ORDER,
    AgentRouter,
    agent_router,
)
from app.agents.consult_guide_agent import (
    WORK_ORDER_WRITE_METHODS,
    consult_guide_agent,
)
from app.agents.work_order_agent import work_order_agent


class TestAgentRouterIntents:
    """至少覆盖：故障咨询、库存只读、引导会话、建单、查单、完工。"""

    def setup_method(self):
        self.router = AgentRouter()

    def test_fault_consult_goes_to_consult(self):
        result = self.router.route("注塑机锁模力不够怎么办？")
        assert result.agent == CONSULT
        assert result.intent == "fault_consult"
        assert result.use_read_tool is False

    def test_inventory_read_only_goes_to_consult(self):
        result = self.router.route("查一下保险丝的库存")
        assert result.agent == CONSULT
        assert result.intent == "inventory_read"

    def test_guided_session_goes_to_consult(self):
        by_text = self.router.route("请按追踪维修一步步排查注塑机报 E3091")
        assert by_text.agent == CONSULT
        assert by_text.intent in ("guided_repair", "expert_repair")
        by_entry = self.router.route("继续上一步", entry="guided-repair/step")
        assert by_entry.agent == CONSULT
        assert by_entry.intent == "guided_repair"
        by_intent = self.router.route("", intent="expert_repair")
        assert by_intent.agent == CONSULT
        assert by_intent.intent == "expert_repair"

    def test_create_work_order_goes_to_work_order_agent(self):
        result = self.router.route("帮我创建一张工单，设备报修锁模力不足")
        assert result.agent == WORK_ORDER
        assert result.intent == "create_work_order"

    def test_query_work_order_goes_to_work_order_agent(self):
        result = self.router.route("查询工单 WO-20260804-002 的进度")
        assert result.agent == WORK_ORDER
        assert result.intent == "query_work_order"
        assert result.use_read_tool is False

    def test_query_work_order_in_guide_session_uses_consult_read_tool(self):
        result = self.router.route(
            "这张工单 WO-20260804-002 现在进度怎么样？",
            in_guide_session=True,
        )
        assert result.intent == "query_work_order"
        assert result.agent == CONSULT
        assert result.use_read_tool is True

    def test_complete_work_order_goes_to_work_order_agent(self):
        result = self.router.route("把这张工单提交完成并完工")
        assert result.agent == WORK_ORDER
        assert result.intent == "complete_work_order"

    def test_explicit_entries_are_stable(self):
        assert self.router.route("", entry="answer/stream").agent == CONSULT
        assert self.router.route("", entry="work-order-create").agent == WORK_ORDER
        assert self.router.route("", entry="work-order-complete").agent == WORK_ORDER
        assert self.router.route("", entry="mcp/query_inventory").agent == CONSULT
        assert self.router.route("", entry="mcp/draft_quote").agent == WORK_ORDER

    def test_write_intent_is_not_redirected_by_guide_session(self):
        result = self.router.route("完成工单", in_guide_session=True)
        assert result.agent == WORK_ORDER
        assert result.intent == "complete_work_order"
        assert result.use_read_tool is False


class TestConsultFacadeCannotWrite:
    def test_consult_facade_exposes_no_work_order_write_apis(self):
        for name in WORK_ORDER_WRITE_METHODS:
            assert not hasattr(consult_guide_agent, name), f"咨询门面不应暴露写方法 {name}"
        assert consult_guide_agent.can_write_work_order() is False

    def test_consult_query_work_order_delegates_to_work_order_read(self, monkeypatch):
        called = {}

        def fake_query(work_order_no: str) -> str:
            called["no"] = work_order_no
            return "只读进度"

        monkeypatch.setattr(work_order_agent, "query_work_order", fake_query)
        text = consult_guide_agent.query_work_order_progress("WO-20260804-002")
        assert called["no"] == "WO-20260804-002"
        assert text == "只读进度"

    def test_consult_invoke_qa_delegates(self, monkeypatch):
        import sys
        import types

        fake = types.ModuleType("app.agents.qa_graph")

        def invoke_qa(question, device_type=None, fault_code=None, top_k=10):
            return {"kind": "fault", "payload": {"cases": []}, "question": question}

        fake.invoke_qa = invoke_qa
        monkeypatch.setitem(sys.modules, "app.agents.qa_graph", fake)
        state = consult_guide_agent.invoke_qa("注塑机温度过高")
        assert state["kind"] == "fault"
        assert state["question"] == "注塑机温度过高"


class TestWorkOrderFacadeWrites:
    def test_work_order_facade_has_write_and_query_methods(self):
        for name in (
            "create_work_order",
            "complete_work_order",
            "query_work_order",
            "import_pdf",
            "analyze_ticket",
            "extract_knowledge",
            "check_dedup",
            "deduct_spare_parts",
        ):
            assert callable(getattr(work_order_agent, name))

    def test_create_and_complete_go_through_write_gate(self):
        created = work_order_agent.create_work_order({"fault_description": "锁模力不足"})
        assert created["accepted"] is True
        assert created["action"] == "create_work_order"
        completed = work_order_agent.complete_work_order(persist=lambda analysis: {"ok": True, "analysis": analysis})
        assert completed["ok"] is True

    def test_create_persist_callback_is_used(self):
        def persist(data):
            return {"saved": data["fault_description"]}

        result = work_order_agent.create_work_order(
            {"fault_description": "油温报警"}, persist=persist,
        )
        assert result == {"saved": "油温报警"}

    def test_analyze_ticket_delegates(self, monkeypatch):
        import sys
        import types

        class Fake:
            def analyze(self, data):
                return {"device_type": data.get("device_type"), "ok": True}

        fake = types.ModuleType("app.agents.ticket_agent")
        fake.ticket_agent = Fake()
        monkeypatch.setitem(sys.modules, "app.agents.ticket_agent", fake)
        result = work_order_agent.analyze_ticket({"device_type": "注塑机"})
        assert result["ok"] is True
        assert result["device_type"] == "注塑机"


class TestSingletonRouter:
    def test_module_singleton_matches_class(self):
        result = agent_router.route("查一下备件库存")
        assert result.agent == CONSULT
