"""对话 LLM 客户端工厂：按 CHAT_LLM_MODE 在云端千问 / 本地 vLLM 之间切换。"""
from __future__ import annotations

from typing import Any, Optional

from langchain_openai import ChatOpenAI

from app.core.config import settings


def make_chat_llm(
    *,
    temperature: float = 0,
    timeout: Optional[float] = None,
    streaming: bool = False,
    max_retries: Optional[int] = None,
    max_tokens: Optional[int] = None,
    model_kwargs: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> ChatOpenAI:
    """构造现网统一的 ChatOpenAI 客户端。调用方只传温度、超时等差异参数。"""
    resolved_timeout = timeout
    if resolved_timeout is not None and settings.chat_llm_mode == "local":
        resolved_timeout = max(float(resolved_timeout), float(settings.CHAT_LOCAL_TIMEOUT_FLOOR))

    params: dict[str, Any] = dict(
        api_key=settings.chat_llm_api_key or "dummy",
        base_url=settings.chat_llm_base_url,
        model=settings.chat_llm_model,
        temperature=temperature,
        streaming=streaming,
        **kwargs,
    )
    if resolved_timeout is not None:
        params["timeout"] = resolved_timeout
    if max_retries is not None:
        params["max_retries"] = max_retries
    if max_tokens is not None:
        params["max_tokens"] = max_tokens
    if model_kwargs is not None:
        params["model_kwargs"] = model_kwargs
    return ChatOpenAI(**params)
