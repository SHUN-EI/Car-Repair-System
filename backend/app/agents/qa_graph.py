"""智能问答入口：AgentRouter 分流 + 故障检索子图。

闲聊与库存是普通函数，不再编译成单节点子图。故障问答仍用 LangGraph 子图，
因为有「预检 → 检索 → 过滤精排」的固定多步拓扑。

由 /api/v1/search/answer/stream 调用，SSE 事件协议不变：
thinking → (suggest_expert) → references → answer 流式 → done

分流走 AgentRouter.qa_kind（库存 / 闲聊 / 故障），不再维护独立的 route_qa_intent。
本入口不会把「查工单进度」自动转到工单只读工具。
"""
from __future__ import annotations

from typing import Optional, Any, TypedDict

from loguru import logger
from langgraph.graph import StateGraph, END
from app.core.config import settings
from app.rag.rag_service import case_rank_score


class QaState(TypedDict, total=False):
    """问答状态：原始问题、可选设备/故障码、路由类型（闲聊/库存/故障），以及各分支的载荷和是否建议切换专家模式。"""
    question: str
    device_type: Optional[str]
    fault_code: Optional[str]
    top_k: int
    kind: str            # chat | inventory | fault
    payload: Any         # chat:str / inventory:AnswerResult / fault:{cases, error_codes, tools}
    error: str
    suggest_expert: bool  # 复合故障提问 → 提示一键切换专家模式


def chat_node(state: QaState) -> dict:
    """闲聊分支：不走检索，直接用回答生成器给出非技术回复。"""
    from app.agents.answer_generator import answer_generator
    q = state.get("question") or ""
    return {"kind": "chat", "payload": answer_generator._answer_non_technical(q)}


def inventory_node(state: QaState) -> dict:
    """库存只读分支：打开临时数据库会话查询库存，结束后关闭。失败时记下错误，不把异常抛出入口外。"""
    from app.agents.answer_generator import answer_generator
    from app.core.database import SessionLocal
    q = state.get("question") or ""
    db = SessionLocal()
    try:
        result = answer_generator.handle_inventory_query(q, db)
        return {"kind": "inventory", "payload": result}
    except Exception as e:
        logger.error(f"[QaGraph] 库存查询失败: {e}")
        return {"kind": "inventory", "payload": None, "error": str(e)}
    finally:
        db.close()


# ============================================================
# 故障检索子图：预检 → 双库检索 → 过滤重排 → 错误码置顶
# ============================================================
def compound_check_node(state: QaState) -> dict:
    """多故障规则预检（连接词 + 多故障信号词，零 LLM 调用）"""
    from app.agents.fault_decomposer import fault_decomposer
    q = state.get("question") or ""
    try:
        if fault_decomposer._looks_compound(q):
            logger.info(f"[QaGraph] 检测到复合故障提问，提示切换专家模式: {q[:50]}")
            return {"suggest_expert": True}
    except Exception as e:
        logger.warning(f"[QaGraph] 多故障检测失败: {e}")
    return {"suggest_expert": False}


def fault_retrieve_node(state: QaState) -> dict:
    """双库检索（公共编排层）：知识库 vector+BM25 + 手册错误码路 → RRF 融合"""
    from app.rag.rag_service import retrieve_hybrid
    q = state.get("question") or ""
    top_k = state.get("top_k") or settings.RECALL_TOP_K
    try:
        merged, error_codes, tools = retrieve_hybrid(
            q, top_k=top_k, device_type=state.get("device_type"),
            fault_code=state.get("fault_code"),
        )
        return {"payload": {"cases": merged, "error_codes": error_codes, "tools": tools}}
    except Exception as e:
        logger.error(f"[QaGraph] 检索阶段失败: {e}")
        return {"payload": {"cases": [], "error_codes": [], "tools": None}}


def fault_filter_node(state: QaState) -> dict:
    """严格过滤 + 加权重排 + 错误码精确置顶（公共编排层）"""
    from app.rag.rag_service import extract_device_and_fault, filter_rerank_cases
    q = state.get("question") or ""
    payload = dict(state.get("payload") or {})
    cases = payload.get("cases") or []
    tools = payload.get("tools")
    error_codes = payload.get("error_codes") or []

    if tools is not None:
        device, kws = extract_device_and_fault(tools, q)
        filtered = filter_rerank_cases(
            tools, cases, q,
            require_device=device, require_keywords=tuple(kws),
            error_codes=error_codes,
        )
    else:
        filtered = [m for m in cases if not m.get("rrf_only", False) and case_rank_score(m) >= settings.RETRIEVAL_COARSE_THRESHOLD][:settings.FINAL_TOP_N]

    payload["cases"] = filtered
    return {"payload": payload}


_fault_graph = StateGraph(QaState)
_fault_graph.add_node("compound_check", compound_check_node)
_fault_graph.add_node("retrieve", fault_retrieve_node)
_fault_graph.add_node("filter", fault_filter_node)
_fault_graph.set_entry_point("compound_check")
_fault_graph.add_edge("compound_check", "retrieve")
_fault_graph.add_edge("retrieve", "filter")
_fault_graph.add_edge("filter", END)
FAULT_SUBGRAPH = _fault_graph.compile()


def invoke_qa(
    question: str,
    device_type: Optional[str] = None,
    fault_code: Optional[str] = None,
    top_k: int = 10,
) -> QaState:
    """智能问答入口：按 AgentRouter.qa_kind 分流，故障分支执行检索子图，返回最终 state。"""
    from app.agents.router import agent_router

    state: QaState = {
        "question": question,
        "device_type": device_type,
        "fault_code": fault_code,
        "top_k": top_k,
    }
    kind = agent_router.qa_kind(question)
    if kind == "chat":
        state.update(chat_node(state))
        return state
    if kind == "inventory":
        state.update(inventory_node(state))
        return state
    fault_state = FAULT_SUBGRAPH.invoke(state)
    fault_state["kind"] = "fault"
    return fault_state
