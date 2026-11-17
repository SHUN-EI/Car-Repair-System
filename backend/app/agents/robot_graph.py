"""钉钉机器人渠道适配器：按 AgentRouter 的 channel_action 分发到处理函数。

本模块不是第一类 Agent，也不再编译 LangGraph。分类统一走 AgentRouter
（consult | work_order），再映射到渠道处理：维修/帮助/库存咨询 → 咨询/引导；
建单提示/待办/查单 → 工单相关处理。

工单查询是「提取工单号再查询」的普通函数。库存短词和设备词兜底已收口到
AgentRouter，none 分支只返回未识别说明。
"""
from __future__ import annotations

import re
from typing import Optional, TypedDict

from loguru import logger

from app.mcp import tools


class RobotState(TypedDict, total=False):
    """钉钉机器人一次请求的状态：用户原文、钉钉和企业用户身份、最终回复，以及工单查询要用的工单号。"""
    text: str                 # 用户消息原文
    staff_id: str             # 钉钉企业 userId（senderStaffId）
    user_id: Optional[int]    # 系统用户 id（未匹配则为 None）
    user_dt_userid: str       # 系统用户的钉钉绑定 userId
    reply: str                # 最终回复
    wo_no: str                # 工单号（供工单查询使用）


class WoSubState(TypedDict, total=False):
    """工单查询用的局部状态：用户原文、解析出的工单号和回复文本。"""
    text: str
    wo_no: str
    reply: str


HELP_TEXT = (
    "您好，我是维修助手，可以帮您：\n"
    "1. 输入工单号（如 WO-20260804-001）查询工单状态\n"
    "2. 发送「我的待办」查看名下待处理工单\n"
    "3. 发送设备名称或故障现象（如 注塑机 温度过高），我会结合历史案例一步一步引导您排查故障；排查过程中把检查结果发给我，我会给出下一步操作\n"
    "4. 发送「查备件库存」（如 保险丝还有多少 / 查一下轴承库存），查询备件库存\n"
    "5. 发送「排班」查询今日排班；「明天排班」「我的排班」可查指定日期或本人排班\n"
    "6. 发送「帮助」或「菜单」查看本说明\n"
    "注：工单录入请在系统『维修报表』中新建；部分功能需先登录系统绑定钉钉。"
)

_CREATE_WO_TEXT = "工单录入暂不支持在钉钉操作，请登录系统在『维修报表』中新建工单。"

_NONE_TEXT = (
    "抱歉，我暂时没有这个功能。\n"
    "我是维修助手，可以帮您：\n"
    "1. 输入工单号查询工单状态\n"
    "2. 发送「我的待办」查看名下待处理工单\n"
    "3. 发送「排班」/「我的排班」查询排班\n"
    "4. 发送「查备件库存」查询库存\n"
    "5. 发送设备名称或故障现象，我会引导您一步步排查\n"
    "发送「帮助」可查看完整功能说明。"
)


def route_intent(state: RobotState, route=None) -> str:
    """把 AgentRouter 的分类结果映射为渠道动作名。可传入已算好的 RouteResult，避免重复分类。"""
    from app.agents.router import agent_router
    text = (state.get("text") or "").strip()
    result = route or agent_router.classify(text, entry="dingtalk")
    action = result.channel_action or ("help" if not text else "repair")
    allowed = {"help", "create", "todo", "workorder", "inventory", "duty", "repair", "none"}
    if action not in allowed:
        action = "repair" if result.agent == "consult" else "todo"
    return action


def help_node(state: RobotState) -> dict:
    """返回机器人功能帮助文案，不访问业务数据。"""
    return {"reply": HELP_TEXT}


def none_node(state: RobotState) -> dict:
    """分类结果为 none 时的说明。库存短词和设备词兜底已在 AgentRouter 完成，这里不再二次分流。"""
    return {"reply": _NONE_TEXT}


def create_node(state: RobotState) -> dict:
    """钉钉里不能直接创建工单，返回引导用户去系统开单的说明。"""
    return {"reply": _CREATE_WO_TEXT}


def todo_node(state: RobotState) -> dict:
    """查询当前绑定用户的待办工单。未识别到系统账号时，提示先在安全设置里绑定钉钉。"""
    staff_id = state.get("staff_id") or ""
    user_id = state.get("user_id")
    if not user_id and not staff_id:
        return {"reply": "未识别到您的系统账号，请先登录系统在『安全设置』中绑定钉钉后再试。"}
    return {"reply": tools.query_my_workorders(staff_id)}


def inventory_node(state: RobotState) -> dict:
    """按用户文本做只读库存查询，并生成回复。"""
    return {"reply": tools.query_inventory(state.get("text") or "")}


def duty_node(state: RobotState) -> dict:
    """按钉钉身份和用户文本查询排班，并生成回复。"""
    return {"reply": tools.query_duty_schedule(state.get("staff_id") or "", state.get("text") or "")}


def repair_node(state: RobotState) -> dict:
    """维修追踪引导入口：三层维修意图阀门校验后再进入 guided_repair_track
    ① regex 错误码 → ② 关键词 → ③ 检索打分：全空返回统一护栏文案（不误导用户继续）"""
    from app.rag.rag_service import (
        make_tools, repair_intent_check, REPAIR_IRRELEVANT_REPLY,
    )
    text = state.get("text") or ""
    # ①② 快判定：无关或短闲聊直接护栏，不跑检索
    from app.rag.rag_service import repair_intent_fast_check
    fast = repair_intent_fast_check(text)
    if fast["decision"] == "irrelevant":
        return {"reply": REPAIR_IRRELEVANT_REPLY + "\n\n" + (
            "另外我也能帮您查工单、待办、排班、库存，发送「帮助」看完整清单。"
        )}
    # related 或 check：必走 repair_intent_check 跑检索判定
    try:
        retrieval_tools = make_tools()
        chk = repair_intent_check(text, retrieval_tools, top_k=5)
    except Exception as e:
        # 检索服务异常时信任 fast_check 放行（宁放行不误拦）
        logger.warning(f"[RobotGraph] 维修意图阀门检索异常，降级放行: {e}")
        chk = {"decision": "related" if fast["decision"] != "irrelevant" else "irrelevant",
               "cases": []}
    if chk["decision"] == "irrelevant":
        return {"reply": REPAIR_IRRELEVANT_REPLY + "\n\n" + (
            "另外我也能帮您查工单、待办、排班、库存，发送「帮助」看完整清单。"
        )}
    # 结构化追踪（联通复用追踪模式）：A/B/C 选项逐步排查；对话式 guided_repair_chat 保留给 MCP 工具
    from app.mcp.tools import guided_repair_track
    return {"reply": guided_repair_track(state.get("staff_id") or "", text)}


def wo_normalize_node(state: WoSubState) -> dict:
    """从用户消息中提取工单号并规范化。"""
    text = state.get("text") or ""
    m = re.search(r"WO[-_ ]?[\d-]{6,}", text, re.IGNORECASE) or re.search(r"\d{6,}", text)
    if not m:
        return {"wo_no": "", "reply": "请输入工单号，例如：WO-20260804-002"}
    no = m.group(0).upper()
    if "WO" not in no:
        no = f"WO-{no}"
    return {"wo_no": no}


def wo_query_node(state: WoSubState) -> dict:
    """按规范化后的工单号查询并格式化回复。"""
    no = state.get("wo_no") or ""
    if not no:
        return {"reply": state.get("reply") or "请输入工单号，例如：WO-20260804-002"}
    return {"reply": tools.query_work_order(no)}


def workorder_node(state: RobotState) -> dict:
    """提取并规范化工单号，再查询并格式化回复。不再使用独立子图。"""
    extracted = wo_normalize_node(state)
    merged = {**state, **extracted}
    return {**extracted, **wo_query_node(merged)}


_ROBOT_HANDLERS = {
    "help": help_node,
    "create": create_node,
    "todo": todo_node,
    "workorder": workorder_node,
    "inventory": inventory_node,
    "duty": duty_node,
    "repair": repair_node,
    "none": none_node,
}


def invoke_robot(
    text: str,
    staff_id: str = "",
    user_id: Optional[int] = None,
    user_dt_userid: str = "",
    route=None,
) -> str:
    """钉钉机器人消息入口：按 AgentRouter 分发到处理函数，返回最终回复。

    若调用方已经分类过，传入 route=RouteResult，避免再跑一遍 LLM 分类。
    """
    state: RobotState = {
        "text": text or "",
        "staff_id": staff_id or "",
        "user_id": user_id,
        "user_dt_userid": user_dt_userid or "",
    }
    action = route_intent(state, route=route)
    handler = _ROBOT_HANDLERS[action]
    result = handler(state)
    return (result or {}).get("reply") or ""
