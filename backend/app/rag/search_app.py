"""检索与问答应用服务：承接原 API 层中的检索编排与回答生成。

HTTP 入口（app.api.search）只负责鉴权、校验、组 JSON/SSE。
本模块不经过 AgentRouter，以保持现网各端点的路由意图不变。
"""
from __future__ import annotations

import asyncio
import json as json_module
import time
from typing import List, Optional

from fastapi import HTTPException
from loguru import logger
from sqlalchemy.orm import Session

from app.agents.answer_generator import answer_generator
from app.agents.consult_guide_agent import consult_guide_agent
from app.agents.expert_repair_agent import ExpertStepResult
from app.agents.tools import RetrievalTools, rrf_merge
from app.core.config import settings
from app.rag.rag_service import (
    make_tools as _make_tools,
    retrieve_hybrid as _retrieve_hybrid,
    extract_device_and_fault as _extract_device_and_fault,
    filter_rerank_cases as _filter_rerank_cases,
    evaluate_retrieval_quality as _evaluate_retrieval_quality,
)


def _effective_score(item: dict) -> float:
    """统一有效分：Reranker精排分 > 向量分 > RRF名次分
    修复：BM25/手册路命中 score 可能为0但 rerank_score 很高，展示/排序/过滤都应取重排后的值"""
    rs = item.get("rerank_score")
    if rs is not None:
        return float(rs)
    vs = item.get("score", 0)
    if vs and vs > 0:
        return float(vs)
    return float(item.get("rrf_score", 0) or 0)

def quick_search(
    q: str,
    device_type: Optional[str] = None,
    fault_code: Optional[str] = None,
    top_k: int = 10,
) -> dict:
    """快速语义检索 - 仅向量检索，适合自动补全等场景"""
    try:
        tools = _make_tools()
        result = tools.vector_search(
            query=q,
            top_k=top_k,
            device_type=device_type,
            fault_code=fault_code,
            score_threshold=settings.RETRIEVAL_VECTOR_THRESHOLD,
        )
        results = []
        for item in result.data:
            results.append({
                "knowledge_id": item.get("knowledge_id") or item.get("id"),
                "title": item.get("title", ""),
                "content": item.get("content", "")[:300],
                "device_type": item.get("device_type", ""),
                "fault_code": item.get("fault_code", ""),
                "fault_tags": item.get("fault_tags", []),
                "score": round(_effective_score(item), 4),
            })
        return {"query": q, "total": len(results), "results": results}
    except Exception as e:
        logger.error(f"快速检索失败: {e}")
        raise HTTPException(status_code=500, detail=f"检索失败: {str(e)}")

def hybrid_search(
    query: str,
    device_type: Optional[str] = None,
    fault_code: Optional[str] = None,
    top_k: int = 10,
) -> dict:
    """向量 + BM25 混合检索 + RRF 融合排序（确定性流程，无 ReAct）"""
    tools = _make_tools()
    import time; start = time.time()

    # 并行执行向量和 BM25 检索
    vector_result = tools.vector_search(
        query=query, 
        top_k=top_k,                           
        device_type=device_type, 
        fault_code=fault_code,
        score_threshold=settings.RETRIEVAL_COARSE_THRESHOLD
        )
    bm25_result = tools.bm25_search(
        query=query, 
        top_k=top_k,
        device_type=device_type, 
        fault_code=fault_code
        )

    # RRF 融合
    result_sets = []
    if vector_result.success:
        result_sets.append(vector_result.data)
    if bm25_result.success:
        result_sets.append(bm25_result.data)

    merged = rrf_merge(result_sets, top_n=top_k) if result_sets else []

    # 格式化输出
    results = []
    for item in merged:
        results.append(dict(
            knowledge_id=item.get("knowledge_id") or item.get("id", 0),
            title=item.get("title", ""),
            content=(item.get("content", "") or "")[:500],
            device_type=item.get("device_type", ""),
            fault_code=item.get("fault_code", ""),
            fault_tags=item.get("fault_tags", []) if isinstance(item.get("fault_tags"), list) else [],
            score=round(_effective_score(item), 4),
            source="hybrid",
        ))

    elapsed = (time.time() - start) * 1000
    return dict(
        query=query,
        mode="hybrid",
        total=len(results),
        results=results,
        strategies_used=["vector_search", "bm25_search"],
        total_time_ms=round(elapsed, 1),
    )

def agent_search(
    query: str,
    device_type: Optional[str] = None,
    fault_code: Optional[str] = None,
    top_k: int = 10,
) -> dict:
    """
    使用 RetrievalAssistantAgent 的完整 ReAct 检索流程。

    流程：思考 → 选择策略 → 执行检索 → 观察结果 → 判断质量 →
          不足则改写查询 → 重试 → 直到满足要求或达到最大迭代次数
    """
    try:
        tools = _make_tools()
        result = consult_guide_agent.search_with_react(
            query=query,
            tools=tools,
            device_type=device_type,
            fault_code=fault_code,
            max_results=top_k,
        )

        # 格式化结果
        results = []
        for item in result.results:
            results.append(dict(
                knowledge_id=item.get("knowledge_id") or item.get("id", 0),
                title=item.get("title", ""),
                content=(item.get("content", "") or "")[:500],
                device_type=item.get("device_type", ""),
                fault_code=item.get("fault_code", ""),
                fault_tags=item.get("fault_tags", []) if isinstance(item.get("fault_tags"), list) else [],
                score=round(_effective_score(item), 4),
                source=result.strategies_used[0] if result.strategies_used else "agent",
            ))

        # 构建 scratchpad 输出
        scratchpad_out = []
        for step in result.scratchpad:
            scratchpad_out.append({
                "step": step.step,
                "thought": step.thought,
                "action": step.action,
                "tool_input": step.tool_input,
                "observation": step.observation,
            })

        return dict(
            query=result.query,
            mode="agent",
            total=len(results),
            results=results,
            strategies_used=result.strategies_used,
            rewrite_count=result.rewrite_count,
            rewritten_queries=result.rewritten_queries,
            total_time_ms=result.total_time_ms,
            scratchpad=scratchpad_out,
        )
    except Exception as e:
        logger.error(f"Agent 检索失败: {e}")
        raise HTTPException(status_code=500, detail=f"Agent 检索失败: {str(e)}")

def manual_lookup(query: str, top_k: int = 5) -> dict:
    """工单"错误码录入"模式预填接口：粘贴设备日志/屏幕原文（或错误码/故障描述），
    返回手册标准处理（权威，带章节/页码出处 + 情形清单）+ 相关工单案例（真实处理记录），
    供前端一键预填工单。"""
    from app.agents.tools import extract_error_codes, rrf_merge, clean_query_for_retrieval
    from app.rag.rag_service import rank_manual_conditions

    tools = _make_tools()
    error_codes = extract_error_codes(query)
    top_k = top_k

    # 日志原文清洗：向量路查询文本剔除时间戳/干扰词，防长日志语义漂移；清洗为空则截断回退
    vector_query = clean_query_for_retrieval(query).strip()
    if not vector_query:
        vector_query = query[:300]

    # 1. 手册路：错误码精确匹配优先，语义检索补充
    manual_items = []
    if error_codes:
        exact = tools.manual_code_search(error_codes, top_k=top_k)
        if exact.success and exact.data:
            manual_items.extend(exact.data)
        vec = tools.manual_vector_search(vector_query, top_k=top_k)
        if vec.success and vec.data:
            seen = {m.get("manual_code_id") for m in manual_items}
            for r in vec.data:
                if r.get("manual_code_id") not in seen:
                    seen.add(r.get("manual_code_id"))
                    manual_items.append(r)
    else:
        vec = tools.manual_vector_search(vector_query, top_k=top_k)
        if vec.success and vec.data:
            manual_items.extend(vec.data)

    # 2. 知识库工单案例：BM25 + 向量双路召回（错误码提问会命中 fault_code/content）
    case_items = []
    try:
        bm25 = tools.bm25_search(query=query, top_k=top_k)
        vector = tools.vector_search(query=vector_query, top_k=top_k, score_threshold=0.0)
        result_sets = [r.data for r in (bm25, vector) if r.success and r.data]
        merged = rrf_merge(result_sets, top_n=top_k) if result_sets else []
        for m in merged:
            case_items.append({
                "knowledge_id": m.get("knowledge_id") or m.get("id", 0),
                "title": m.get("title", ""),
                "content": (m.get("content", "") or "")[:300],
                "device_type": m.get("device_type", ""),
                "fault_code": m.get("fault_code", ""),
            })
    except Exception as e:
        logger.error(f"manual-lookup 知识库案例检索失败: {e}")

    # 3. 手册条目情形排序（伴随信号匹配）+ 转输出（带结构化字段）
    manual_items = rank_manual_conditions(manual_items, query)
    out_manual = []
    for m in manual_items:
        out_manual.append({
            "manual_code_id": m.get("manual_code_id"),
            "error_code": m.get("error_code", ""),
            "title": m.get("title", ""),
            "description": m.get("description", "") or "",
            "message_text": m.get("message_text", "") or "",
            "severity": m.get("severity", "") or "",
            "effect": m.get("effect", "") or "",
            "conditions": m.get("conditions", []) or [],
            "related_codes": m.get("related_codes", []) or [],
            "matched_signals": m.get("matched_signals", []) or [],
            "causes": m.get("causes", "") or "",
            "solutions": m.get("solutions", "") or "",
            "manual_name": m.get("manual_name", ""),
            "chapter": m.get("chapter", ""),
            "page": m.get("page", ""),
            "device_type": m.get("device_type", ""),
        })

    return {
        "query": query,
        "error_codes": error_codes,
        "manual_items": out_manual,
        "case_items": case_items,
    }

def _run_agent_search(tools: RetrievalTools, query: str, device_type: Optional[str],
                      fault_code: Optional[str], top_k: int,
                      require_hybrid: bool = False) -> List[dict]:
    """在独立线程中执行一次 ReAct Agent 检索（供多故障并行调用）"""
    result = consult_guide_agent.search_with_react(
        query=query,
        tools=tools,
        device_type=device_type,
        fault_code=fault_code,
        max_results=top_k,
        require_hybrid=require_hybrid,
    )
    return result.results


def _pipeline_first_with_rescue(tools: RetrievalTools, query: str,
                                device_type: Optional[str], fault_code: Optional[str],
                                top_k: int) -> List[dict]:
    """专家模式检索核心：管道四路优先 → 阀门判定 → 不达标才 ReAct 救援。

    ① 先跑确定性的四路管道（retrieve_hybrid + 严格过滤 + 精排 + 置顶），零 LLM 决策，秒级返回。
    ② 用公共阀门 evaluate_retrieval_quality 判定结果是否充分（≥3 条且（高分≥2 或最高分≥0.7））。
    ③ 充分 → 直接返回（省掉 ReAct 延迟）；不足 → ReAct 救援（原必跑行为）→ 严格过滤收口。
    返回已严格过滤 + 精排的最终案例列表，供首轮分组 / 单故障分支直接使用。
    """
    merged, error_codes, tools = _retrieve_hybrid(query, top_k=top_k, device_type=device_type)
    device, kws = _extract_device_and_fault(tools, query)
    cases = _filter_rerank_cases(tools, merged, query,
                                 require_device=device, require_keywords=tuple(kws),
                                 error_codes=error_codes)
    # 管道充分 → 直接交付，省掉 ReAct 延迟
    if _evaluate_retrieval_quality(cases)["sufficient"]:
        return cases

    # 管道不足 → ReAct 救援（首轮强制 vector+BM25 双路），再严格过滤收口
    logger.info(f"[Expert] 管道检索质量不足，触发 ReAct 救援: {query[:50]}")
    rescue_results = _run_agent_search(tools, query, device_type, fault_code, top_k, True)
    device, kws = _extract_device_and_fault(tools, query)
    return _filter_rerank_cases(tools, rescue_results, query,
                                require_device=device, require_keywords=tuple(kws))


def _to_reference(ref: dict, fault: str = "") -> dict:
    """把检索结果转为前端参考案例格式；手册条目带 source_type + 出处字段，多故障时带 fault 归属标签"""
    is_manual = ref.get("manual_code_id") is not None
    item = {
        "knowledge_id": ref.get("knowledge_id") or ref.get("manual_code_id") or ref.get("id", 0),
        "source_type": "MANUAL" if is_manual else "CASE",   # 来源类型：手册 / 工单案例
        "title": ref.get("title", ""),
        "content": (ref.get("content", "") or "")[:200],
        "device_type": ref.get("device_type", ""),
        "fault_code": ref.get("fault_code", ""),
        "score": round(_effective_score(ref), 4),
        "summary": ref.get("summary", ""),
    }
    # 手册条目出处：错误码 + 手册名 + 章节 + 页码（前端展示/回溯用）
    if is_manual:
        item["error_code"] = ref.get("error_code", "")
        item["manual_name"] = ref.get("manual_name", "")
        item["chapter"] = ref.get("chapter", "")
        item["page"] = ref.get("page", "")
    if fault:
        item["fault"] = fault
    return item

async def iter_analyze_answer_sse(
    question: str,
    device_type: Optional[str] = None,
    fault_code: Optional[str] = None,
    top_k: Optional[int] = 8,
    scene: Optional[str] = None,
):
    """SSE 事件流：检修问答（不经过 AgentRouter，保持现网路由意图）。"""
    # 立即响应，让前端显示"正在思考..."
    yield f"data: {json_module.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"

    # 三层维修意图阀门（只对最终 kind=fault 生效；chat/inventory 原本就无需检索）
    from app.rag.rag_service import (
        make_tools, repair_intent_check, REPAIR_IRRELEVANT_REPLY,
    )
    tools = make_tools()

    # 走 LangGraph 主图 + 子图：意图路由（聊天/库存/故障）→ 对应子图执行。
    t_retrieve_start = time.monotonic()
    try:
        state = await asyncio.to_thread(
            consult_guide_agent.invoke_qa,
            question, device_type, fault_code, top_k,
        )
    except Exception as e:
        t_retrieve = (time.monotonic() - t_retrieve_start) * 1000
        logger.error(f"[Answer/stream] 阶段=检索 异常耗时={t_retrieve:.0f}ms")
        logger.error(f"[Answer] 智能问答图执行失败: {e}")
        yield f"data: {json_module.dumps({'type': 'answer', 'content': f'服务异常: {e}'}, ensure_ascii=False)}\n\n"
        yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
        return

    kind = state.get("kind", "fault")
    payload = state.get("payload")

    # ---- 库存子图：一次性文本回答 ----
    if kind == "inventory":
        answer_text = getattr(payload, "answer", None) if payload is not None else None
        if not answer_text:
            answer_text = "库存查询服务暂时不可用，请稍后重试。"
        yield f"data: {json_module.dumps({'type': 'answer', 'content': answer_text}, ensure_ascii=False)}\n\n"
        yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
        return

    # ---- 聊天子图：问候/功能介绍，一次性文本回答 ----
    if kind == "chat":
        yield f"data: {json_module.dumps({'type': 'answer', 'content': payload or ''}, ensure_ascii=False)}\n\n"
        yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
        return

    # ---- 故障子图：复合故障提示 → 参考案例 → 流式生成 ----
    # 统一三层阀门：①②全不命中且检索 cases 空/低分 → 直接护栏回复，不调用 LLM 生成
    cases = (payload or {}).get("cases") or []
    if not cases:
        # qa_graph 已跑 retrieve_hybrid + filter_rerank_cases + 宽松降级还空
        # 此时再走一次独立的 repair_intent_check（复用规则+相同检索逻辑保证口径）
        chk = repair_intent_check(
            question, tools, device_type,
            top_k=top_k or 8,
        )
        if chk["decision"] == "irrelevant":
            logger.info(f"[Answer/stream] 阶段=意图阀门 判定=irrelevant")
            yield f"data: {json_module.dumps({'type': 'answer', 'content': REPAIR_IRRELEVANT_REPLY}, ensure_ascii=False)}\n\n"
            yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
            return
        # 阀门判为 related 但 qa_graph cases 为空（罕见：不同参数下的差异），仍按原链路走
        cases = chk["cases"]

    t_retrieve = (time.monotonic() - t_retrieve_start) * 1000
    t_ref_start = time.monotonic()
    logger.info(f"[Answer/stream] 阶段=检索 done 耗时={t_retrieve:.0f}ms cases={len(cases)} kind={kind}")

    if state.get("suggest_expert"):
        yield f"data: {json_module.dumps({'type': 'suggest_expert'}, ensure_ascii=False)}\n\n"

    references = [_to_reference(ref) for ref in cases[:8]]
    yield f"event: references\ndata: {json_module.dumps(references, ensure_ascii=False)}\n\n"
    t_ref = (time.monotonic() - t_ref_start) * 1000
    logger.info(f"[Answer/stream] 阶段=参考案例组装 done 耗时={t_ref:.0f}ms refs={len(references)}")

    t_gen_start = time.monotonic()
    try:
        for sse_msg in answer_generator.stream_answer(
            question, cases, scene=scene or "",
        ):
            yield sse_msg
    except Exception as e:
        t_gen = (time.monotonic() - t_gen_start) * 1000
        logger.error(f"[Answer/stream] 阶段=生成 异常耗时={t_gen:.0f}ms")
        logger.error(f"流式生成失败: {e}")
        yield f"data: {json_module.dumps({'type': 'answer', 'content': f'生成失败: {e}'}, ensure_ascii=False)}\n\n"
        yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': len(references)}, ensure_ascii=False)}\n\n"
    else:
        t_gen = (time.monotonic() - t_gen_start) * 1000
        logger.info(f"[Answer/stream] 阶段=生成 done 耗时={t_gen:.0f}ms")


async def iter_expert_answer_sse(
    question: str,
    device_type: Optional[str] = None,
    fault_code: Optional[str] = None,
    top_k: Optional[int] = 8,
    db: Optional[Session] = None,
):
    """SSE 事件流：专家模式（首轮）。"""
    yield f"data: {json_module.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"

    # Step 0: 库存查询前置（与普通问答保持一致）
    if answer_generator.is_inventory_query(question):
        from app.models.spare_part import SparePart
        result = answer_generator.handle_inventory_query(question, db)
        yield f"data: {json_module.dumps({'type': 'answer', 'content': result.answer}, ensure_ascii=False)}\n\n"
        yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
        return

    tools = _make_tools()

    # Step 1: 复合问题拆解（规则预检 + LLM 拆解，单故障直通）
    try:
        sub_queries = await asyncio.wait_for(
            asyncio.to_thread(consult_guide_agent.decompose_fault, question),
            timeout=20,            # 拆解超时 20s → 按单故障处理，不让用户干等
        )
    except asyncio.TimeoutError:
        logger.warning(f"[Expert] 问题拆解超时，按单故障处理: {question[:50]}")
        sub_queries = [question]
    sub_queries = sub_queries or [question]

    # ===== 多故障：分组并行（管道优先 + ReAct 救援）检索 + 分组回答 =====
    if len(sub_queries) > 1:
        try:
            per_fault_results = await asyncio.wait_for(
                asyncio.gather(*[
                    asyncio.to_thread(
                        _pipeline_first_with_rescue, tools, sq,
                        device_type, fault_code, top_k,
                    )
                    for sq in sub_queries
                ]),
                timeout=90,        # 并行检索整体超时 90s，超时降级为"未检索到"而不是挂死
            )
        except asyncio.TimeoutError:
            logger.error("[Expert] 多故障并行检索超时，本次返回空结果")
            per_fault_results = [[] for _ in sub_queries]
        except Exception as e:
            logger.error(f"[Expert] 多故障并行检索失败: {e}")
            per_fault_results = [[] for _ in sub_queries]

        # 统一三层阀门：所有子故障 cases 全空 → 再跑 repair_intent_check 确认
        if not any(per_fault_results):
            chk = repair_intent_check(
                question, tools, device_type,
                top_k=top_k or 8,
            )
            if chk["decision"] == "irrelevant":
                yield f"data: {json_module.dumps({'type': 'answer', 'content': REPAIR_IRRELEVANT_REPLY}, ensure_ascii=False)}\n\n"
                yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
                return

        faults = []
        references = []
        for sq, res in zip(sub_queries, per_fault_results):
            cases = res  # 已严格过滤 + 精排
            faults.append({"name": sq, "cases": cases})
            for ref in cases:
                references.append(_to_reference(ref, fault=sq))
        # 参考案例跨故障全局按匹配度降序（高匹配度在上面，故障标签仍保留）
        references.sort(key=lambda x: x.get("score", 0), reverse=True)
        references = references[:8]

        # 首轮增强：共因/关联判定 + 维修优先级 + 2-3 个方向选项（新增，供多轮引导）
        first_round = consult_guide_agent.expert_first_round(question, faults)
        session_id = consult_guide_agent.expert_create_session(
            question, sub_queries, faults, first_round["analysis"])

        yield f"data: {json_module.dumps({'type': 'answer', 'content': first_round['analysis']}, ensure_ascii=False)}\n\n"
        yield f"event: references\ndata: {json_module.dumps(references, ensure_ascii=False)}\n\n"

        try:
            for sse_msg in answer_generator.stream_answer_multi(question, faults, emit_done=False):
                yield sse_msg
        except Exception as e:
            logger.error(f"[Expert] 多故障流式生成失败: {e}")
            yield f"data: {json_module.dumps({'type': 'answer', 'content': '生成失败，请稍后重试。'}, ensure_ascii=False)}\n\n"

        # 引导选项 + 完成事件（done 携带 session_id 供前端发起后续引导轮）
        yield f"event: options\ndata: {json_module.dumps(first_round['options'], ensure_ascii=False)}\n\n"
        yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': len(references), 'session_id': session_id}, ensure_ascii=False)}\n\n"
        return

    # ===== 单故障：管道优先 + ReAct 救援 + 五段式分析回答 =====
    filtered_merged = []
    try:
        filtered_merged = await asyncio.wait_for(
            asyncio.to_thread(_pipeline_first_with_rescue, tools, sub_queries[0],
                              device_type, fault_code, top_k),
            timeout=60,            # 单故障检索超时 60s
        )
    except asyncio.TimeoutError:
        logger.error("[Expert] 单故障检索超时")
        filtered_merged = []
    except Exception as e:
        logger.error(f"[Expert] 检索失败: {e}")
        filtered_merged = []

    # 统一三层阀门：cases 全空且 retrieval_empty → 护栏
    if not filtered_merged:
        chk = repair_intent_check(
            question, tools, device_type,
            top_k=top_k or 8,
        )
        if chk["decision"] == "irrelevant":
            yield f"data: {json_module.dumps({'type': 'answer', 'content': REPAIR_IRRELEVANT_REPLY}, ensure_ascii=False)}\n\n"
            yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
            return
        filtered_merged = chk["cases"]  # 阀门可能给了 related cases

    references = [_to_reference(ref) for ref in filtered_merged[:8]]
    faults_single = [{"name": sub_queries[0], "cases": filtered_merged}]

    # 首轮增强：单故障也生成"定位分析 + 优先级 + 方向选项"并创建会话（供多轮引导）
    first_round = consult_guide_agent.expert_first_round(question, faults_single)
    session_id = consult_guide_agent.expert_create_session(
        question, sub_queries, faults_single, first_round["analysis"])

    yield f"data: {json_module.dumps({'type': 'answer', 'content': first_round['analysis']}, ensure_ascii=False)}\n\n"
    yield f"event: references\ndata: {json_module.dumps(references, ensure_ascii=False)}\n\n"

    try:
        for sse_msg in answer_generator.stream_answer(question, filtered_merged, emit_done=False):
            yield sse_msg
    except Exception as e:
        logger.error(f"[Expert] 流式生成失败: {e}")
        yield f"data: {json_module.dumps({'type': 'answer', 'content': '生成失败，请稍后重试。'}, ensure_ascii=False)}\n\n"

    yield f"event: options\ndata: {json_module.dumps(first_round['options'], ensure_ascii=False)}\n\n"
    yield f"data: {json_module.dumps({'type': 'done', 'confidence': 0, 'sources_count': len(references), 'session_id': session_id}, ensure_ascii=False)}\n\n"


async def iter_expert_next_step_sse(session_id: str, message: str):
    """SSE 事件流：专家模式后续引导轮。"""
    yield f"data: {json_module.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(consult_guide_agent.expert_next_step, session_id, message),
            timeout=90,          # 引导轮超时 90s（检索+精排+LLM 生成），超时给可感知的降级提示
        )
    except asyncio.TimeoutError:
        logger.error("[Expert] 专家引导轮超时")
        result = ExpertStepResult(session_id=session_id,
                                  analysis="引导生成超时，请补充执行结果或设备状态后重试。")
    except Exception as e:
        logger.error(f"[Expert] 专家引导轮失败: {e}")
        result = ExpertStepResult(session_id=session_id,
                                  analysis="引导生成失败，请稍后重试。")

    yield f"data: {json_module.dumps({'type': 'answer', 'content': result.analysis}, ensure_ascii=False)}\n\n"
    if result.summary:
        yield f"data: {json_module.dumps({'type': 'answer', 'content': result.summary}, ensure_ascii=False)}\n\n"
    options = [{"id": o.id, "cause": o.cause, "diagnostic_action": o.diagnostic_action}
               for o in result.options]
    yield f"event: options\ndata: {json_module.dumps(options, ensure_ascii=False)}\n\n"
    done_payload = json_module.dumps({
        "type": "done",
        "session_id": result.session_id,
        "completed": result.status == "completed",
        "summary": result.summary,
    }, ensure_ascii=False)
    yield f"data: {done_payload}\n\n"

