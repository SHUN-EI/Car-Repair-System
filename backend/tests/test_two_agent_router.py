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
        """每个用例前准备路由器测试所需的默认状态。"""
        self.router = AgentRouter()

    def test_fault_consult_goes_to_consult(self):
        """故障咨询应路由到咨询/引导 Agent。"""
        result = self.router.route("注塑机锁模力不够怎么办？")
        assert result.agent == CONSULT
        assert result.intent == "fault_consult"
        assert result.use_read_tool is False

    def test_inventory_read_only_goes_to_consult(self):
        """只读库存查询应路由到咨询 Agent。"""
        result = self.router.route("查一下保险丝的库存")
        assert result.agent == CONSULT
        assert result.intent == "inventory_read"

    def test_guided_session_goes_to_consult(self):
        """已在引导维修会话中的请求应保持咨询 Agent。"""
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
        """创建工单应路由到工单 Agent。"""
        result = self.router.route("帮我创建一张工单，设备报修锁模力不足")
        assert result.agent == WORK_ORDER
        assert result.intent == "create_work_order"

    def test_query_work_order_goes_to_work_order_agent(self):
        """查询工单默认路由到工单 Agent。"""
        result = self.router.route("查询工单 WO-20260804-002 的进度")
        assert result.agent == WORK_ORDER
        assert result.intent == "query_work_order"
        assert result.use_read_tool is False

    def test_query_work_order_in_guide_session_uses_consult_read_tool(self):
        """引导会话中查询工单时，主责任仍是咨询 Agent，只用只读工具。"""
        result = self.router.route(
            "这张工单 WO-20260804-002 现在进度怎么样？",
            in_guide_session=True,
        )
        assert result.intent == "query_work_order"
        assert result.agent == CONSULT
        assert result.use_read_tool is True

    def test_complete_work_order_goes_to_work_order_agent(self):
        """完成工单应路由到工单 Agent。"""
        result = self.router.route("把这张工单提交完成并完工")
        assert result.agent == WORK_ORDER
        assert result.intent == "complete_work_order"

    def test_explicit_entries_are_stable(self):
        """显式入口（HTTP/MCP）的意图映射应稳定，不再二次文本分类。"""
        assert self.router.route("", entry="answer/stream").agent == CONSULT
        assert self.router.route("", entry="work-order-create").agent == WORK_ORDER
        assert self.router.route("", entry="work-order-complete").agent == WORK_ORDER
        assert self.router.route("", entry="mcp/query_inventory").agent == CONSULT
        assert self.router.route("", entry="mcp/draft_quote").agent == WORK_ORDER

    def test_write_intent_is_not_redirected_by_guide_session(self):
        """即使在引导会话中，写工单意图也不能改派给咨询 Agent。"""
        result = self.router.route("完成工单", in_guide_session=True)
        assert result.agent == WORK_ORDER
        assert result.intent == "complete_work_order"
        assert result.use_read_tool is False


class TestConsultFacadeCannotWrite:
    """咨询门面不能写工单。"""
    def test_consult_facade_exposes_no_work_order_write_apis(self):
        """咨询门面不应暴露创建、完成工单等写接口。"""
        for name in WORK_ORDER_WRITE_METHODS:
            assert not hasattr(consult_guide_agent, name), f"咨询门面不应暴露写方法 {name}"
        assert consult_guide_agent.can_write_work_order() is False

    def test_consult_query_work_order_delegates_to_work_order_read(self, monkeypatch):
        """咨询侧查工单应转给工单 Agent 的只读方法。"""
        called = {}

        def fake_query(work_order_no: str) -> str:
            """假的工单只读查询，用于确认咨询门面会转调它。"""
            called["no"] = work_order_no
            return "只读进度"

        monkeypatch.setattr(work_order_agent, "query_work_order", fake_query)
        text = consult_guide_agent.query_work_order_progress("WO-20260804-002")
        assert called["no"] == "WO-20260804-002"
        assert text == "只读进度"

    def test_consult_invoke_qa_delegates(self, monkeypatch):
        """咨询门面的问答调用应转给问答入口 invoke_qa。"""
        import sys
        import types

        fake = types.ModuleType("app.agents.qa_graph")

        def invoke_qa(question, device_type=None, fault_code=None, top_k=10):
            """假的问答调用，用于确认咨询门面会转给问答入口。"""
            return {"kind": "fault", "payload": {"cases": []}, "question": question}

        fake.invoke_qa = invoke_qa
        monkeypatch.setitem(sys.modules, "app.agents.qa_graph", fake)
        state = consult_guide_agent.invoke_qa("注塑机温度过高")
        assert state["kind"] == "fault"
        assert state["question"] == "注塑机温度过高"


class TestWorkOrderFacadeWrites:
    """工单门面的写操作和查询方法。"""
    def test_work_order_facade_has_write_and_query_methods(self):
        """工单门面应同时具备写操作和只读查询方法。"""
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
        """创建和完成工单必须先经过写权限守门。"""
        created = work_order_agent.create_work_order({"fault_description": "锁模力不足"})
        assert created["accepted"] is True
        assert created["action"] == "create_work_order"
        completed = work_order_agent.complete_work_order(persist=lambda analysis: {"ok": True, "analysis": analysis})
        assert completed["ok"] is True

    def test_create_persist_callback_is_used(self):
        """创建工单时应调用调用方传入的 persist 回调来落库。"""
        def persist(data):
            """测试用的落库回调，确认创建工单时会被调用。"""
            return {"saved": data["fault_description"]}

        result = work_order_agent.create_work_order(
            {"fault_description": "油温报警"}, persist=persist,
        )
        assert result == {"saved": "油温报警"}

    def test_analyze_ticket_delegates(self, monkeypatch):
        """分析工单应转给工单理解 Agent。"""
        import sys
        import types

        class Fake:
            """假的工单理解模块，用于确认分析请求被转交。"""
            def analyze(self, data):
                """返回带入参标记的假分析结果。"""
                return {"device_type": data.get("device_type"), "ok": True}

        fake = types.ModuleType("app.agents.ticket_agent")
        fake.ticket_agent = Fake()
        monkeypatch.setitem(sys.modules, "app.agents.ticket_agent", fake)
        result = work_order_agent.analyze_ticket({"device_type": "注塑机"})
        assert result["ok"] is True
        assert result["device_type"] == "注塑机"


class TestSingletonRouter:
    """模块级路由器单例。"""
    def test_module_singleton_matches_class(self):
        """模块导出的 agent_router 单例与类的路由结果一致。"""
        result = agent_router.route("查一下备件库存")
        assert result.agent == CONSULT

class TestUnifiedQaKindAndGraphShape:
    """问答分流收口到 AgentRouter 后，图只保留故障检索与 PDF 导入。"""

    def setup_method(self):
        """每个用例前准备路由器。"""
        self.router = AgentRouter()

    def test_qa_kind_inventory_chat_and_fault(self):
        """库存问句走 inventory，问候与非技术残留走 chat，技术故障走 fault。"""
        assert self.router.qa_kind("查一下保险丝的库存") == "inventory"
        assert self.router.qa_kind("你好") == "chat"
        assert self.router.qa_kind("谢谢") == "chat"
        assert self.router.qa_kind("注塑机温度过高") == "fault"

    def test_qa_kind_does_not_hand_work_order_progress_to_work_order_agent(self):
        """HTTP 问答入口仍不自动改派工单进度，只在闲聊或故障检索中分流。"""
        kind = self.router.qa_kind("查询工单 WO-20260804-002 的进度")
        assert kind in ("chat", "fault")

    def test_short_part_name_is_inventory_only_on_dingtalk_path(self):
        """短备件名仅在钉钉路径按库存处理；问答入口仍按故障检索，行为与改前一致。"""
        dingtalk = self.router.classify("保险丝", entry="dingtalk")
        assert dingtalk.intent == "inventory_read"
        assert dingtalk.channel_action == "inventory"
        assert self.router.qa_kind("保险丝") == "fault"
        hello = self.router.classify("你好", entry="dingtalk")
        assert hello.channel_action == "help"

    def test_qa_graph_keeps_only_fault_subgraph(self):
        """qa_graph 不再编译闲聊/库存子图和问答主图。"""
        from pathlib import Path
        import ast

        src = Path(__file__).resolve().parents[1].joinpath("app/agents/qa_graph.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        assigned = {n.targets[0].id for n in ast.walk(tree) if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}
        assert "FAULT_SUBGRAPH" in assigned
        assert "CHAT_SUBGRAPH" not in assigned
        assert "INVENTORY_SUBGRAPH" not in assigned
        assert "QA_GRAPH" not in assigned
        assert "def invoke_qa" in src

    def test_robot_graph_has_no_langgraph(self):
        """钉钉适配器改为函数分发，源码中不再编译 StateGraph。"""
        from pathlib import Path
        import ast

        src = Path(__file__).resolve().parents[1].joinpath("app/agents/robot_graph.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("langgraph"):
                imported.add(n.module)
            if isinstance(n, ast.Import):
                for alias in n.names:
                    if alias.name.startswith("langgraph"):
                        imported.add(alias.name)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert not imported
        assert "StateGraph" not in names
        assert "ROBOT_GRAPH" not in names
        assert "WO_SUBGRAPH" not in names
        assert "def invoke_robot" in src
