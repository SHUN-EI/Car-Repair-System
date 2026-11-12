"""意图路由器 AgentRouter：渠道入参 → consult | work_order。

每个请求只派给一个 Agent 作为主责任方。HTTP / 前端 / 钉钉 / MCP 都是渠道，
不是第三 Agent。本模块只做分发，不实现检索或工单状态机。

咨询过程中若问到某张工单进度/内容，且已处于引导会话，主责任方仍是咨询/引导，
通过工单 Agent 的只读工具查询；创建、改状态、审批、完工、扣料等写操作必须交给工单 Agent。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# 第一类 Agent 名称（对外只承认这两个）
CONSULT = "consult"
WORK_ORDER = "work_order"

# 明确意图 → 主 Agent
INTENT_TO_AGENT = {
    "fault_consult": CONSULT,
    "manual_qa": CONSULT,
    "chitchat": CONSULT,
    "feature_intro": CONSULT,
    "help": CONSULT,
    "inventory_read": CONSULT,
    "guided_repair": CONSULT,
    "expert_repair": CONSULT,
    "duty": CONSULT,  # 排班只读查询，归咨询侧渠道能力，不写入工单
    "query_work_order": WORK_ORDER,
    "create_work_order": WORK_ORDER,
    "import_work_order": WORK_ORDER,
    "dispatch": WORK_ORDER,
    "transition_status": WORK_ORDER,
    "approve": WORK_ORDER,
    "complete_work_order": WORK_ORDER,
    "deduct_parts": WORK_ORDER,
    "quote": WORK_ORDER,
    "package": WORK_ORDER,
    "knowledge_extract": WORK_ORDER,
    "knowledge_dedup": WORK_ORDER,
    "todo": WORK_ORDER,
}

# HTTP / 显式入口 → 意图（路径已能确定主责任方时，不再按文本二次分类）
ENTRY_TO_INTENT = {
    "answer/stream": "fault_consult",
    "answer/expert": "expert_repair",
    "answer/expert/step": "expert_repair",
    "guided-repair": "guided_repair",
    "guided-repair/start": "guided_repair",
    "guided-repair/step": "guided_repair",
    "guided-repair/chat": "guided_repair",
    "search/agent": "fault_consult",
    "search/hybrid": "fault_consult",
    "manual-lookup": "manual_qa",
    "session/summarize": "fault_consult",
    "dingtalk": None,  # 钉钉需按文本分类
    "mcp/search_knowledge": "fault_consult",
    "mcp/guided_repair": "guided_repair",
    "mcp/query_inventory": "inventory_read",
    "mcp/query_work_order": "query_work_order",
    "mcp/query_my_workorders": "todo",
    "mcp/recommend_service": "package",
    "mcp/draft_quote": "quote",
    "mcp/query_compatible_parts": "query_work_order",  # 工单录入关联备件，归工单只读工具
    "work-order-create": "create_work_order",
    "work-order-import": "import_work_order",
    "work-order-query": "query_work_order",
    "work-order-complete": "complete_work_order",
    "work-order-transition": "transition_status",
    "work-order-dispatch": "dispatch",
    "work-order-approve": "approve",
    "work-order-deduct": "deduct_parts",
    "work-order-analyze": "create_work_order",
    "work-order-quote": "quote",
    "work-order-package": "package",
    "knowledge-extract": "knowledge_extract",
    "knowledge-dedup": "knowledge_dedup",
}

# 钉钉渠道细分类标签（适配器节点名，不是第三 Agent）
INTENT_TO_ROBOT_ACTION = {
    "help": "help",
    "feature_intro": "help",
    "chitchat": "help",
    "create_work_order": "create",
    "import_work_order": "create",
    "todo": "todo",
    "complete_work_order": "todo",
    "approve": "todo",
    "dispatch": "todo",
    "transition_status": "todo",
    "deduct_parts": "todo",
    "query_work_order": "workorder",
    "quote": "todo",
    "package": "todo",
    "knowledge_extract": "todo",
    "knowledge_dedup": "todo",
    "inventory_read": "inventory",
    "duty": "duty",
    "guided_repair": "repair",
    "expert_repair": "repair",
    "fault_consult": "repair",
    "manual_qa": "repair",
}

# 钉钉节点 → 主 Agent（避免渠道再维护一套互斥分类）
ROBOT_ACTION_TO_AGENT = {
    "help": CONSULT,
    "inventory": CONSULT,
    "duty": CONSULT,
    "repair": CONSULT,
    "none": CONSULT,
    "create": WORK_ORDER,
    "todo": WORK_ORDER,
    "workorder": WORK_ORDER,
}


@dataclass(frozen=True)
class RouteResult:
    """一次路由的结果。"""
    agent: str                 # consult | work_order
    intent: str                # 细粒度意图
    source: str                # entry | intent | keyword | llm | default
    use_read_tool: bool = False  # 咨询主会话中查询工单时，走只读工具
    channel_action: str = ""   # 钉钉适配器节点名（help/create/todo/...），无则空


class AgentRouter:
    """渠道入参到两个第一类 Agent 的薄路由。"""

    # 写操作关键词：必须先于「查工单」匹配，避免「完成工单」被当成查询
    _WRITE_RULES = (
        (re.compile(r"(导入).{0,8}(工单|PDF)|工单导入"), "import_work_order"),
        (re.compile(r"(创建|新增|录入|开单).{0,6}工单|工单(录入|创建|新增)|报修"), "create_work_order"),
        (re.compile(r"派工"), "dispatch"),
        (re.compile(r"(审批|批准).{0,4}工单|工单(审批|批准)"), "approve"),
        (re.compile(r"(完成工单|工单完工|提交完成|标记完工|完工工单)"), "complete_work_order"),
        (re.compile(r"(扣料|扣减备件|备件出库|出库扣减)"), "deduct_parts"),
        (re.compile(r"(改状态|状态流转|流转工单)"), "transition_status"),
        (re.compile(r"(生成报价|报价草案|报价(单)?(落地|应用到工单)|套餐(推荐)?(落地|应用到工单))"), "quote"),
        (re.compile(r"(提取知识|知识去重|沉淀知识|工单.{0,6}(入库知识|收录知识))"), "knowledge_extract"),
    )
    _QUERY_WO_RE = re.compile(
        r"(查询?工单|工单(进度|内容|详情|状态|情况)|工单号)"
        r"|WO[-_ ]?[\d-]{6,}"
        r"|(?<!\d)\d{6,}(?!\d)",
        re.IGNORECASE,
    )
    _GUIDED_RE = re.compile(r"(追踪维修|一步步(查|排|引导)|逐步(排查|引导)|专家模式)")
    _INVENTORY_READ_RE = re.compile(
        r"(查(一下)?(库存|备件)|备件库存|库存查询|"
        r"有没有.{0,12}(配件|备件|库存|保险丝)|"
        r"查(一下)?.{0,16}(库存|备件))"
    )
    _HELP_RE = re.compile(r"(帮助|菜单|功能介绍|功能说明|\bhelp\b|\bhello\b|你好)")
    _TODO_RE = re.compile(r"(我的待办|我的工单|待办|代办)")
    _DUTY_RE = re.compile(r"(排班|值班|班表|班次)")
    _PACKAGE_RE = re.compile(r"(保养套餐|套餐推荐)")

    def agent_for_intent(self, intent: str) -> str:
        """细粒度意图到主 Agent。未知意图默认归咨询/引导，避免误触发工单写操作。"""
        return INTENT_TO_AGENT.get(intent, CONSULT)

    def agent_for_robot_action(self, action: str) -> str:
        """钉钉节点名到主 Agent。"""
        return ROBOT_ACTION_TO_AGENT.get(action, CONSULT)

    def route(
        self,
        text: str = "",
        *,
        entry: Optional[str] = None,
        intent: Optional[str] = None,
        in_guide_session: bool = False,
        use_llm: bool = False,
    ) -> RouteResult:
        """将渠道入参映射到 consult | work_order。

        优先级：显式 intent > 显式 entry（钉钉入口除外）> 文本关键词 > 可选 LLM > 默认故障咨询。
        in_guide_session 为 True 且意图是查工单时，主责任方仍是咨询（只读工具），写操作不受影响。
        """
        if intent:
            agent = self.agent_for_intent(intent)
            use_read = self._should_use_read_tool(intent, in_guide_session, agent)
            if use_read:
                agent = CONSULT
            return RouteResult(
                agent=agent,
                intent=intent,
                source="intent",
                use_read_tool=use_read,
                channel_action=INTENT_TO_ROBOT_ACTION.get(intent, ""),
            )

        if entry and entry not in ("dingtalk", "mcp"):
            mapped = ENTRY_TO_INTENT.get(entry)
            if mapped:
                agent = self.agent_for_intent(mapped)
                use_read = self._should_use_read_tool(mapped, in_guide_session, agent)
                if use_read:
                    agent = CONSULT
                return RouteResult(
                    agent=agent,
                    intent=mapped,
                    source="entry",
                    use_read_tool=use_read,
                    channel_action=INTENT_TO_ROBOT_ACTION.get(mapped, ""),
                )

        keyword = self._classify_by_keywords(text or "")
        if keyword is not None:
            return self._finalize(keyword, "keyword", in_guide_session)

        # 库存只读：复用问答侧已有判定，避免与 qa_graph 口径漂移
        if self._is_inventory_query(text or ""):
            return self._finalize("inventory_read", "keyword", in_guide_session)

        if use_llm or entry == "dingtalk":
            llm_intent = self._classify_with_llm_fallback(text or "")
            if llm_intent:
                return self._finalize(llm_intent, "llm", in_guide_session)

        return self._finalize("fault_consult", "default", in_guide_session)

    def classify(self, text: str, *, entry: Optional[str] = None, in_guide_session: bool = False) -> RouteResult:
        """钉钉 / 自然语言渠道的分类入口，与 route() 同一套规则。"""
        use_llm = entry == "dingtalk"
        return self.route(text, entry=entry, in_guide_session=in_guide_session, use_llm=use_llm)

    def _finalize(self, intent: str, source: str, in_guide_session: bool) -> RouteResult:
        agent = self.agent_for_intent(intent)
        use_read = self._should_use_read_tool(intent, in_guide_session, agent)
        if use_read:
            agent = CONSULT
        action = INTENT_TO_ROBOT_ACTION.get(intent, "")
        if intent == "chitchat" and source == "llm":
            action = "none"
        return RouteResult(
            agent=agent,
            intent=intent,
            source=source,
            use_read_tool=use_read,
            channel_action=action,
        )

    @staticmethod
    def _should_use_read_tool(intent: str, in_guide_session: bool, agent: str) -> bool:
        return bool(in_guide_session and intent == "query_work_order" and agent == WORK_ORDER)

    def _classify_by_keywords(self, text: str) -> Optional[str]:
        text = (text or "").strip()
        if not text:
            return "help"
        if any(k in text for k in ("帮助", "菜单", "功能")) or text.lower() in ("help", "hello"):
            return "help"
        if text in ("你好", "您好"):
            return "chitchat"
        for pattern, intent in self._WRITE_RULES:
            if pattern.search(text):
                return intent
        if self._QUERY_WO_RE.search(text):
            return "query_work_order"
        if self._TODO_RE.search(text):
            return "todo"
        if self._PACKAGE_RE.search(text):
            return "package"
        if self._GUIDED_RE.search(text):
            return "guided_repair" if "专家" not in text else "expert_repair"
        if self._INVENTORY_READ_RE.search(text):
            return "inventory_read"
        if self._DUTY_RE.search(text):
            return "duty"
        if self._HELP_RE.search(text):
            return "help"
        return None

    @staticmethod
    def _is_inventory_query(text: str) -> bool:
        try:
            from app.agents.answer_generator import answer_generator
            return bool(answer_generator.is_inventory_query(text))
        except Exception:
            return False

    def _classify_with_llm_fallback(self, text: str) -> Optional[str]:
        """复用钉钉适配器已有的 LLM 分类，作为关键词未命中时的兜底；映射回统一意图。

        LLM 与关键词规则都集中在本路由器，渠道不再单独维护互斥分类器。
        """
        text = (text or "").strip()
        if not text:
            return "help"
        # 纯设备名：与原 robot_graph 快速通道一致，走维修引导
        try:
            from app.agents.tools import get_device_terms
            dev_terms = get_device_terms()
            stripped = text.strip()
            for t in sorted(dev_terms, key=len, reverse=True):
                if stripped == t:
                    return "guided_repair"
        except Exception:
            dev_terms = []
        label = ""
        try:
            from app.agents.robot_graph import _classify_intent_llm
            label = _classify_intent_llm(text) or ""
        except Exception:
            label = ""
        if label == "none":
            try:
                from app.agents.tools import get_device_terms
                if any(t in text for t in get_device_terms() if t and len(t) >= 2):
                    return "guided_repair"
            except Exception:
                pass
            return "chitchat"
        if label:
            return self._intent_from_robot_label(label)
        # LLM 失败时的规则兜底（与原 robot_graph 一致）
        if self._TODO_RE.search(text) or any(k in text for k in ("任务",)):
            return "todo"
        if self._DUTY_RE.search(text):
            return "duty"
        try:
            from app.agents.tools import get_device_terms
            if any(t in text for t in get_device_terms() if t and len(t) >= 2):
                return "guided_repair"
        except Exception:
            pass
        return "fault_consult"

    @staticmethod
    def _intent_from_robot_label(label: str) -> str:
        mapping = {
            "help": "help",
            "create": "create_work_order",
            "todo": "todo",
            "workorder": "query_work_order",
            "inventory": "inventory_read",
            "duty": "duty",
            "repair": "guided_repair",
            "none": "chitchat",
        }
        return mapping.get(label, "fault_consult")


agent_router = AgentRouter()
