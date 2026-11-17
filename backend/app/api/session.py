"""会话管理 API - 摘要压缩"""
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List
from loguru import logger

from app.agents.consult_guide_agent import consult_guide_agent
from app.core.rate_limit import hit
from app.core.security import get_current_user
from app.models.user import User

router = APIRouter()


class MessageItem(BaseModel):
    """会话里的一条消息：角色只能是 user 或 assistant，内容不能为空。"""
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


class SummarizeRequest(BaseModel):
    """请求压缩会话历史：会话 ID，以及至少两条待压缩消息。"""
    session_id: str = Field(..., description="会话ID")
    messages: List[MessageItem] = Field(..., min_length=2, description="待压缩的消息列表")


class SummarizeResponse(BaseModel):
    """会话摘要结果：摘要文本、被压缩的消息条数和耗时。"""
    session_id: str
    summary: str
    compressed_count: int
    time_ms: float


@router.post("/summarize", response_model=SummarizeResponse, summary="会话摘要压缩")
def summarize_session(request: SummarizeRequest, current_user: User = Depends(get_current_user)):
    """将会话历史消息压缩为结构化摘要，用于替代原始消息降低存储"""
    hit(f"session-summarize:{current_user.id}", limit=10, window_seconds=60)
    start = time.time()
    try:
        messages_dict = [{"role": m.role, "content": m.content} for m in request.messages]
        summary = consult_guide_agent.summarize(messages_dict)
        elapsed = (time.time() - start) * 1000
        return SummarizeResponse(
            session_id=request.session_id,
            summary=summary,
            compressed_count=len(request.messages),
            time_ms=round(elapsed, 1),
        )
    except Exception as e:
        logger.error(f"会话摘要失败: {e}")
        raise HTTPException(status_code=500, detail=f"摘要生成失败: {str(e)}")
