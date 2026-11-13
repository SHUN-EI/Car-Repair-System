"""知识检索 API - 混合检索（向量 + BM25 + RRF）+ ReAct Agent + 分析型问答

鉴权、参数校验与 HTTP/SSE 组装留在本层；检索编排与回答生成见 app.rag.search_app。
"""
from fastapi import APIRouter, Query, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy.orm import Session
from loguru import logger

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.rate_limit import hit
from app.models.user import User
from app.agents.consult_guide_agent import consult_guide_agent
from app.rag import search_app

router = APIRouter()


# ==================== 请求/响应模型 ====================
# Pydantic 数据模型（数据契约）：只定义接口的数据结构，不执行任何逻辑。
# FastAPI 用它自动完成：①校验请求 ②JSON↔Python对象转换 ③生成 Swagger 文档。

class SearchRequest(BaseModel):
    """搜索请求：客户端发来"搜什么"时的数据格式"""
    query: str = Field(..., description="搜索关键词或自然语言描述")      # 必填（... = 无默认值，必须传）
    device_type: Optional[str] = Field(None, description="设备类型筛选")  # 可选，不传=不过滤（如"注塑机"）
    fault_code: Optional[str] = Field(None, description="故障码筛选")    # 可选，不传=不过滤（如"6401"）
    top_k: Optional[int] = Field(10, ge=1, le=50)                        # 返回条数：默认10，限制1~50
    mode: Optional[str] = Field("agent", description="检索模式: agent | hybrid | vector | bm25")  # 检索策略，默认agent


class SearchResultItem(BaseModel):
    """单条搜索结果：对应前端展示的一张知识卡片"""
    knowledge_id: int              # 知识库主键（全局唯一身份，RRF融合的去重键）
    title: str                     # 案例标题
    content: str                   # 案例正文内容
    device_type: Optional[str] = ""    # 设备类型（默认空串，避免前端显示 undefined）
    fault_code: Optional[str] = ""     # 故障码（默认空串）
    fault_tags: Optional[List[str]] = []  # 故障标签数组（如["温控","加热器"]）
    score: float                   # 相关度分数 0~1，越接近1越相关（各接口口径不同，见接口实现）
    source: str  # vector / bm25 / conditional / graph   # 这条结果来自哪条检索路


class SearchResponse(BaseModel):
    """搜索接口的整体响应：把多条结果 + 检索元信息打包返回"""
    query: str                                   # 回显用户搜索的原话
    mode: str                                    # 这次实际走的检索模式（agent / hybrid 等）
    total: int                                   # 返回结果总数
    results: List[SearchResultItem]              # 结果列表（每个元素是上面那个模型）
    strategies_used: List[str] = []              # 实际用了哪几条检索策略（如 vector_search / bm25_search）
    rewrite_count: int = 0                       # 查询改写了几次（仅 /agent 有值）
    rewritten_queries: List[str] = []            # 改写出来的查询词列表
    total_time_ms: float = 0.0                   # 总耗时（毫秒）
    scratchpad: Optional[List[dict]] = None      # Agent 的推理过程（思考/行动/观察），仅 /agent 返回，调试用


class AnswerRequest(BaseModel):
    """问答请求：客户端发来"问一个问题"时的数据格式"""
    question: str = Field(..., description="用户的维修问题")     # 必填，问题文本
    device_type: Optional[str] = Field(None, description="设备类型筛选")  # 可选，缩小检索范围
    fault_code: Optional[str] = Field(None, description="故障码筛选")    # 可选，缩小检索范围
    top_k: Optional[int] = Field(10, ge=3, le=20)   # 检索案例数：默认10，限制3~20（至少3条供LLM参考）
    session_id: Optional[str] = Field(None, description="专家模式会话ID（多轮引导时带上前一轮返回的 session_id）")
    scene: Optional[str] = Field(None, description="consult=车主问诊，空则保持原维修问答")


class ExpertStepRequest(BaseModel):
    """专家模式后续引导轮请求：带会话ID + 用户反馈"""
    session_id: str = Field(..., min_length=1, max_length=64, description="专家模式会话ID（首轮 done 事件返回）")
    message: str = Field(..., min_length=1, max_length=1000, description="用户反馈：执行结果 / 设备状态 / 选中的排查方向")
    device_type: Optional[str] = Field(None, description="设备类型筛选（可选）")


class ManualLookupRequest(BaseModel):
    """工单错误码录入预填请求：粘贴设备日志/屏幕原文或错误码，返回手册标准处理 + 工单案例"""
    query: str = Field(..., min_length=1, max_length=2000, description="设备日志/屏幕原文（或错误码，如 SV0436 / 6401）")
    top_k: Optional[int] = Field(5, ge=1, le=10, description="每类返回条数上限")


# ==================== 工具工厂 ====================
# _make_tools 已移至 RAG 门面 app.rag.rag_service.make_tools（顶部 import 别名引用）
# ==================== API 端点 ====================


@router.get("/quick", summary="快速语义检索")
def quick_search(
    q: str = Query(..., description="搜索内容"),
    device_type: Optional[str] = Query(None),
    fault_code: Optional[str] = Query(None),
    top_k: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """快速语义检索 - 仅向量检索，适合自动补全等场景"""
    return search_app.quick_search(
        q=q, device_type=device_type, fault_code=fault_code, top_k=top_k,
    )


@router.post("/hybrid", response_model=SearchResponse, summary="混合检索（无Agent）")
def hybrid_search(
    request: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """向量 + BM25 混合检索 + RRF 融合排序（确定性流程，无 ReAct）"""
    return search_app.hybrid_search(
        query=request.query,
        device_type=request.device_type,
        fault_code=request.fault_code,
        top_k=request.top_k,
    )


@router.post("/agent", response_model=SearchResponse, summary="Agent 智能检索（ReAct 循环）")
def agent_search(
    request: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    使用 RetrievalAssistantAgent 的完整 ReAct 检索流程。

    流程：思考 → 选择策略 → 执行检索 → 观察结果 → 判断质量 →
          不足则改写查询 → 重试 → 直到满足要求或达到最大迭代次数
    """
    hit(f"search-agent:{current_user.id}", limit=20, window_seconds=60)
    return search_app.agent_search(
        query=request.query,
        device_type=request.device_type,
        fault_code=request.fault_code,
        top_k=request.top_k,
    )


@router.post("/manual-lookup", summary="错误码录入预填检索（手册 + 工单案例）")
def manual_lookup(
    request: ManualLookupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """工单"错误码录入"模式预填接口：粘贴设备日志/屏幕原文（或错误码/故障描述），
    返回手册标准处理（权威，带章节/页码出处 + 情形清单）+ 相关工单案例（真实处理记录），
    供前端一键预填工单。"""
    return search_app.manual_lookup(query=request.query, top_k=request.top_k)


@router.post("/answer/stream", summary="分析型问答（流式 SSE）")
async def analyze_answer_stream(
    request: AnswerRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return StreamingResponse(
        search_app.iter_analyze_answer_sse(
            question=request.question,
            device_type=request.device_type,
            fault_code=request.fault_code,
            top_k=request.top_k,
            scene=request.scene,
        ),
        media_type="text/event-stream",
    )


@router.post("/answer/expert", summary="专家问答（流式 SSE）— 多故障拆解 + ReAct 智能检索 + 生成式回答")
async def expert_answer_stream(
    request: AnswerRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return StreamingResponse(
        search_app.iter_expert_answer_sse(
            question=request.question,
            device_type=request.device_type,
            fault_code=request.fault_code,
            top_k=request.top_k,
            db=db,
        ),
        media_type="text/event-stream",
    )


@router.post("/answer/expert/step", summary="专家模式下一步（多轮引导：分析+引导）")
async def expert_next_step(request: ExpertStepRequest,
                          current_user=Depends(get_current_user)):
    """专家模式后续引导轮：用户反馈执行结果 → AI 判断是否解决，给出下一步 2-3 个方向

    SSE 事件（与首轮 /answer/expert 一致）：
    - {"type": "thinking"} — 思考中
    - {"type": "answer", "content": "..."} — 【分析】+ 引导说明（含是否解决判断）
    - event: options — 2-3 个方向选项（按优先级排序，第 1 个为推荐）
    - {"type": "done", "session_id": "...", "completed": true/false, "summary": "..."}
    """
    return StreamingResponse(
        search_app.iter_expert_next_step_sse(
            session_id=request.session_id,
            message=request.message,
        ),
        media_type="text/event-stream",
    )


# ==================== 追踪维修引导 ====================

class GuidedRepairStartRequest(BaseModel):
    description: str = Field(..., min_length=2, max_length=500)
    device_type: Optional[str] = None


class GuidedRepairStepRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    selected_option: str = Field(..., description="选择的选项ID，如 A/B/C")
    action_taken: str = Field(..., min_length=1, max_length=1000, description="执行了什么操作")
    device_status: str = Field(..., min_length=1, max_length=500, description="操作后设备状态")


class RepairOptionOut(BaseModel):
    id: str
    cause: str
    diagnostic_action: str


class GuidedRepairStepOut(BaseModel):
    session_id: str
    step: int
    message: str
    options: List[RepairOptionOut] = []
    status: str = "awaiting_action"
    summary: str = ""


@router.post("/guided-repair/start", response_model=GuidedRepairStepOut, summary="开始追踪维修")
def start_guided_repair(request: GuidedRepairStartRequest,
                      current_user = Depends(get_current_user)):
    """根据故障描述启动追踪维修诊断"""
    result = consult_guide_agent.start_guided_repair(
        description=request.description,
        device_type=request.device_type or "",
    )
    return GuidedRepairStepOut(
        session_id=result.session_id,
        step=result.step,
        message=result.message,
        options=[RepairOptionOut(id=o.id, cause=o.cause, diagnostic_action=o.diagnostic_action)
                 for o in result.options],
        status=result.status,
        summary=result.summary,
    )


@router.post("/guided-repair/{session_id}/step", response_model=GuidedRepairStepOut, summary="追踪维修下一步")
def guided_repair_next_step(session_id: str, request: GuidedRepairStepRequest,
                           current_user = Depends(get_current_user)):
    """维修员反馈操作结果，AI 给出下一步诊断"""
    result = consult_guide_agent.guided_repair_next_step(
        session_id=session_id,
        selected_option=request.selected_option,
        action_taken=request.action_taken,
        device_status=request.device_status,
    )
    return GuidedRepairStepOut(
        session_id=result.session_id,
        step=result.step,
        message=result.message,
        options=[RepairOptionOut(id=o.id, cause=o.cause, diagnostic_action=o.diagnostic_action)
                 for o in result.options],
        status=result.status,
        summary=result.summary,
    )


# ==================== 对话式追踪维修（流式） ====================

class GuidedRepairChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="维修员消息")
    session_id: Optional[str] = Field(None, description="追踪会话ID，首次为空则自动创建")
    device_type: Optional[str] = Field(None, description="设备类型")
    scene: Optional[str] = Field(None, description="consult=车主问诊，空则保持原追踪维修")


@router.post("/guided-repair/chat", summary="对话式追踪维修（流式 SSE）")
async def guided_repair_chat_stream(request: GuidedRepairChatRequest,
                                    current_user = Depends(get_current_user)):
    """对话式追踪维修：维修员发自然语言消息，AI 流式返回引导回复。

    事件类型：
    - {"type": "thinking"} — AI 正在检索分析中
    - {"type": "answer", "content": "..."} — 片段内容
    - {"type": "done", "session_id": "xxx"} — 完成
    """
    import json as json_module
    import uuid
    import asyncio

    sid = request.session_id or str(uuid.uuid4())

    async def stream():
        yield f"data: {json_module.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"

        try:
            # 使用新的 achat 异步方法，原生 async for，无死锁风险
            async for chunk in consult_guide_agent.guided_repair_achat(
                session_id=sid,
                message=request.message,
                device_type=request.device_type or "",
                scene=request.scene or "",
            ):
                if hasattr(chunk, 'content') and chunk.content:
                    yield f"data: {json_module.dumps({'type': 'answer', 'content': chunk.content}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"[GuidedChat] 流式生成失败: {e}")
            yield f"data: {json_module.dumps({'type': 'answer', 'content': f'生成失败: {str(e)[:100]}'}, ensure_ascii=False)}\n\n"

        yield f"data: {json_module.dumps({'type': 'done', 'session_id': sid}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
