"""钉钉等自然语言渠道共用的 LLM 意图分类器。

分类结果只作为 AgentRouter 的兜底输入，渠道适配器不要直接调用本模块做分发。
标签集合与钉钉 channel_action 对齐：help / create / todo / workorder /
inventory / duty / repair / none。
"""
from __future__ import annotations

from loguru import logger


_INTENT_HINTS = {
    "help": "查看帮助/功能菜单",
    "create": "录入工单/报修",
    "todo": "查询我的待办/名下工单/任务",
    "workorder": "按工单号查询工单",
    "inventory": "查询备件库存",
    "duty": "查询排班/值班表",
    "repair": "设备故障排查求助/引导维修",
    "none": "与上述功能均无关的内容（闲聊、其他领域的问题等）",
}

_INTENT_PROMPT = """你是维修助手的意图分类器。根据用户消息从以下意图中选择一个，只输出意图名本身，不要解释：
{choices}

规则：
- 只有当消息确实涉及某个功能时才返回对应意图名；
- 如果消息与所有功能都无关（如闲聊、开玩笑、非维修领域问题），必须返回 none；
- 只有消息明确描述了具体设备或故障现象（如 注塑机、电机、PLC、温度过高、不运转、报警 等）时才返回 repair；
- 描述模糊、无法对应到具体设备或故障时返回 none；
- 不要臆测，不确定时返回 none。

用户消息：{text}"""

_llm_classifier = None


def _get_llm_classifier():
    """懒加载意图分类器（与对话链路同一套 make_chat_llm 配置）。"""
    global _llm_classifier
    if _llm_classifier is None:
        from app.core.chat_llm import make_chat_llm
        _llm_classifier = make_chat_llm(
            temperature=0,
            timeout=15,
        )
    return _llm_classifier


def classify_intent_llm(text: str) -> str:
    """用 LLM 做意图分类，失败或结果未知返回空串。"""
    try:
        from langchain_core.messages import HumanMessage
        choices = "\n".join(f"- {k}：{v}" for k, v in _INTENT_HINTS.items())
        resp = _get_llm_classifier().invoke([
            HumanMessage(content=_INTENT_PROMPT.format(choices=choices, text=text)),
        ])
        label = (resp.content or "").strip().lower()
        for k in _INTENT_HINTS:
            if k in label:
                return k
        logger.warning(f"[IntentClassifier] LLM 意图分类返回未知结果: {label!r}")
    except Exception as e:
        logger.warning(f"[IntentClassifier] LLM 意图分类失败，回退规则: {e}")
    return ""
