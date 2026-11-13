"""咨询/引导 Agent 门面。

职责：面向维修员或车主的咨询、诊断与逐步引导，不直接改写工单状态。
本模块只做编排委托，检索阈值、RRF 与报价规则仍留在既有模块。

内部能力（兼容别名，不是并列的第三 Agent）：
- 智能问答主图 qa_graph
- 追踪维修 Redis 状态机 guided_repair_agent（TTL 24h，最多 30 步）
- 专家模式 Redis 状态机 expert_repair_agent / fault_decomposer
- 有上限的检索 ReAct retrieval_agent
- 会话摘要 session_summarizer

查询工单进度时，可调用工单 Agent 的只读工具；创建、改状态、审批、完工、扣料
等写操作不在本门面暴露。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# 工单写操作方法名：本门面不得实现。测试据此锁定边界。
WORK_ORDER_WRITE_METHODS = (
    "create_work_order",
    "import_pdf",
    "transition_status",
    "approve_work_order",
    "complete_work_order",
    "deduct_spare_parts",
    "apply_quote",
    "apply_package",
)


class ConsultGuideAgent:
    """咨询/引导门面：问答 / 引导 / 专家。不暴露工单写 API。"""

    name = "consult"

    # ---------- 智能问答 ----------
    def invoke_qa(
        self,
        question: str,
        device_type: Optional[str] = None,
        fault_code: Optional[str] = None,
        top_k: int = 10,
    ):
        """委托问答主图。SSE 事件仍由 HTTP 层按原协议组装。"""
        from app.agents.qa_graph import invoke_qa
        return invoke_qa(
            question,
            device_type=device_type,
            fault_code=fault_code,
            top_k=top_k,
        )

    def search_with_react(
        self,
        query: str,
        tools=None,
        device_type: Optional[str] = None,
        fault_code: Optional[str] = None,
        max_results: int = 10,
        require_hybrid: bool = False,
    ):
        """委托有上限的 ReAct 检索循环。不改检索阈值。"""
        from app.agents.retrieval_agent import RetrievalAssistantAgent
        if tools is None:
            from app.rag.rag_service import make_tools
            tools = make_tools()
        agent = RetrievalAssistantAgent(tools=tools)
        return agent.search(
            query=query,
            device_type=device_type,
            fault_code=fault_code,
            max_results=max_results,
            require_hybrid=require_hybrid,
        )

    def answer_from_retrieval(self, query: str, top_k: int = 10) -> str:
        """渠道（MCP 等）用的同步问答：公共检索编排 + 生成器。不改融合公式。"""
        if not query or not query.strip():
            return "请输入故障描述，例如：注塑机 温度过高"
        try:
            from app.rag.rag_service import (
                retrieve_hybrid, extract_device_and_fault, filter_rerank_cases,
            )
            from app.agents.answer_generator import answer_generator
            merged, error_codes, tools = retrieve_hybrid(query, top_k=top_k)
            device, kws = extract_device_and_fault(tools, query)
            cases = filter_rerank_cases(
                tools, merged, query, top_n=5,
                require_device=device, require_keywords=tuple(kws),
                error_codes=error_codes,
            )
            result = answer_generator.answer(query, cases)
            return result.answer
        except Exception as e:
            from loguru import logger
            logger.warning(f"[ConsultGuide] 知识检索失败: {e}")
            return "知识检索暂时不可用，请稍后再试或直接联系资深工程师。"

    def query_inventory_readonly(self, question: str, db=None) -> str:
        """口头库存查询，只读。写出入库仍归工单/进销存。"""
        from app.agents.answer_generator import answer_generator
        close_db = False
        if db is None:
            from app.core.database import SessionLocal
            db = SessionLocal()
            close_db = True
        try:
            result = answer_generator.handle_inventory_query(question, db)
            return getattr(result, "answer", None) or str(result)
        finally:
            if close_db:
                db.close()

    # ---------- 追踪维修（多轮不上图，Redis 状态机） ----------
    def start_guided_repair(self, description: str, device_type: str = ""):
        from app.agents.guided_repair_agent import guided_repair_agent
        return guided_repair_agent.start_diagnosis(
            description=description, device_type=device_type or "",
        )

    def guided_repair_next_step(
        self,
        session_id: str,
        selected_option: str,
        action_taken: str,
        device_status: str,
    ):
        from app.agents.guided_repair_agent import guided_repair_agent
        return guided_repair_agent.next_step(
            session_id=session_id,
            selected_option=selected_option,
            action_taken=action_taken,
            device_status=device_status,
        )

    def guided_repair_chat(self, session_id: str, message: str, device_type: str = ""):
        from app.agents.guided_repair_agent import guided_repair_agent
        return guided_repair_agent.chat(
            session_id=session_id, message=message, device_type=device_type or "",
        )

    def guided_repair_chat_sync(self, session_id: str, message: str, device_type: str = "") -> str:
        from app.agents.guided_repair_agent import guided_repair_agent
        return guided_repair_agent.chat_sync(
            session_id, message, device_type=device_type or "",
        )

    def guided_repair_achat(
        self,
        session_id: str,
        message: str,
        device_type: str = "",
        scene: str = "",
    ):
        from app.agents.guided_repair_agent import guided_repair_agent
        return guided_repair_agent.achat(
            session_id=session_id,
            message=message,
            device_type=device_type or "",
            scene=scene or "",
        )

    def guided_session_status(self, session_id: str):
        from app.agents.guided_repair_agent import guided_repair_agent
        return guided_repair_agent.get_session_status(session_id)

    def guided_current_options(self, session_id: str):
        from app.agents.guided_repair_agent import guided_repair_agent
        return guided_repair_agent.get_current_options(session_id)

    # ---------- 专家模式（多轮不上图） ----------
    def decompose_fault(self, question: str) -> List[str]:
        from app.agents.fault_decomposer import fault_decomposer
        return fault_decomposer.decompose(question)

    def expert_first_round(self, question: str, faults: List[Dict]) -> Dict:
        from app.agents.expert_repair_agent import expert_repair_agent
        return expert_repair_agent.generate_first_round(question, faults)

    def expert_create_session(
        self,
        question: str,
        sub_queries: List[str],
        faults: List[Dict],
        first_analysis: str,
    ) -> str:
        from app.agents.expert_repair_agent import expert_repair_agent
        return expert_repair_agent.create_session(
            question, sub_queries, faults, first_analysis,
        )

    def expert_next_step(self, session_id: str, message: str):
        from app.agents.expert_repair_agent import expert_repair_agent
        return expert_repair_agent.next_step(session_id, message)

    # ---------- 会话摘要 ----------
    def summarize(self, messages: List[dict]) -> str:
        from app.memory.memory_service import memory_service
        return memory_service.summarize(messages)

    # ---------- 工单只读工具（写操作不在本门面） ----------
    def query_work_order_progress(self, work_order_no: str) -> str:
        """咨询过程中查询工单进度/内容：转调工单 Agent 只读方法。"""
        from app.agents.work_order_agent import work_order_agent
        return work_order_agent.query_work_order(work_order_no)

    def can_write_work_order(self) -> bool:
        return False


consult_guide_agent = ConsultGuideAgent()
