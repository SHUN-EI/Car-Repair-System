"""工单 Agent 门面。

职责：工单从进入系统到关闭，以及由工单沉淀知识。
定价与状态迁移由规则/状态机执行，LLM 只做理解、抽取和草稿；本模块不重写
检索阈值、报价算术或工单编号规则。

内部能力（兼容别名，不是并列的第三 Agent）：
- 工单理解 ticket_agent
- 导入 DAG work_order_importer
- 生命周期（由 API / domain.work_order_status 落库，本门面为写操作入口）
- 报价与套餐规则引擎 service_tools / quote_service
- 配件关联 inventory_tools
- 知识沉淀 knowledge_extractor / dedup_agent
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional


# 工单写操作（咨询/引导门面不得暴露这些方法）
WRITE_ACTIONS = (
    "create_work_order",
    "import_pdf",
    "transition_status",
    "approve_work_order",
    "complete_work_order",
    "deduct_spare_parts",
    "apply_quote",
    "apply_package",
)

_STATUS_CN = {
    "DRAFT": "草稿",
    "SUBMITTED": "待审核",
    "ASSIGNED": "已指派",
    "ACCEPTED": "已接单",
    "ARRIVED": "已到场",
    "INSPECTING": "检修中",
    "IN_PROGRESS": "维修中",
    "ARCHIVING": "待归档",
    "ARCHIVED": "已归档",
    "COMPLETED": "已完成",
    "REJECTED": "已驳回",
    "STANDARDIZED": "已标准化",
    "CLASSIFIED": "已分类",
    "APPROVED": "已审核",
    "INTAKE": "接车",
    "DIAGNOSING": "诊断中",
    "QUOTING": "报价中",
    "QC": "质检",
    "CLOSED": "已结案",
    "CANCELLED": "已取消",
}


def _status_cn(status) -> str:
    raw = status.value if hasattr(status, "value") else str(status)
    return _STATUS_CN.get(raw, raw)


def _normalize_work_order_no(raw: str) -> str:
    """将用户各种输入规范化为 WO-YYYYMMDD-XXX（与渠道原逻辑一致）。"""
    no = (raw or "").strip().upper().replace(" ", "").replace("_", "-")
    if not no:
        return no
    m = re.match(r"WO-?(\d{8})-?(\d+)$", no)
    if m:
        return f"WO-{m.group(1)}-{m.group(2)}"
    if no.startswith("WO") and re.match(r"WO-?\d{4,}$", no):
        return no.replace("WO", "WO-", 1) if no.startswith("WO") and no[2] != "-" else no
    return no


class WorkOrderAgent:
    """工单门面：理解 / 导入 / 生命周期 / 沉淀。报价走规则引擎，不交给 LLM 定价。"""

    name = "work_order"

    def claim_write(self, action: str) -> str:
        """HTTP/渠道写接口的责任方标记。不改变既有校验与状态机。"""
        if action not in WRITE_ACTIONS:
            raise ValueError(f"未知工单写操作: {action}")
        return action

    # ---------- 工单理解 ----------
    def analyze_ticket(self, work_order_data: Dict[str, Any]):
        from app.agents.ticket_agent import ticket_agent
        return ticket_agent.analyze(work_order_data)

    # ---------- 导入 DAG（确认前只写草稿） ----------
    def import_pdf(self, pdf_path: str, file_name: str, batch_id: int) -> dict:
        from app.agents.work_order_importer import invoke_import_pdf
        return invoke_import_pdf(pdf_path, file_name, batch_id)

    # ---------- 知识沉淀 ----------
    def extract_knowledge(self, work_order_data: Dict):
        from app.agents.knowledge_extractor import knowledge_extractor
        return knowledge_extractor.extract(work_order_data)

    def check_dedup(self, new_item: dict, existing_item: dict, title_similarity: float = 0.0):
        from app.agents.dedup_agent import dedup_agent
        return dedup_agent.check(new_item, existing_item, title_similarity=title_similarity)

    # ---------- 配件关联（工单录入时使用） ----------
    def query_inventory(self, *args, **kwargs):
        from app.agents.inventory_tools import query_inventory
        return query_inventory(*args, **kwargs)

    def list_compatible_parts(self, *args, **kwargs):
        from app.agents.inventory_tools import list_compatible_parts
        return list_compatible_parts(*args, **kwargs)

    def resolve_fitment_spec(self, *args, **kwargs):
        from app.agents.inventory_tools import resolve_fitment_spec
        return resolve_fitment_spec(*args, **kwargs)

    # ---------- 套餐 / 报价（规则引擎，LLM 不得改价格） ----------
    def recommend_packages(self, db, **kwargs) -> dict:
        from app.agents.service_tools import recommend_service_packages
        return recommend_service_packages(db, **kwargs)

    def format_recommendation(self, result: dict) -> str:
        from app.agents.service_tools import format_recommendation
        return format_recommendation(result)

    def create_draft_quote(self, db, **kwargs):
        """生成报价草案。价格由 quote_service 规则计算，不经 LLM。"""
        from app.domain.quote_service import create_draft
        return create_draft(db, **kwargs)

    def apply_quote(self, db, **kwargs):
        """将报价/套餐结果应用到工单的写入口；具体状态仍走领域服务。"""
        self.claim_write("apply_quote")
        return self.create_draft_quote(db, **kwargs)

    def apply_package(self, db, **kwargs) -> dict:
        self.claim_write("apply_package")
        return self.recommend_packages(db, **kwargs)

    # ---------- 只读查询 ----------
    def query_work_order(self, work_order_no: str) -> str:
        """按工单号查询进度与内容（只读，可供咨询/引导调用）。"""
        if not work_order_no or not str(work_order_no).strip():
            return "请输入工单号，例如：WO-20260804-002"
        no = _normalize_work_order_no(work_order_no)
        from app.core.database import SessionLocal
        from app.models.work_order import WorkOrder
        from app.models.user import User
        db = SessionLocal()
        try:
            wo = db.query(WorkOrder).filter(WorkOrder.work_order_no == no).first()
            if not wo:
                return f"未找到工单 {no}，请确认工单号是否正确。"
            status = _status_cn(wo.status)
            tech = None
            if wo.technician_id:
                tech = db.query(User).filter(User.id == wo.technician_id).first()
            lines = [
                f"### 工单 {wo.work_order_no}",
                f"- 设备：{wo.device_code or '-'}",
                f"- 故障：{wo.fault_description or '-'}",
                f"- 状态：**{status}**",
                f"- 优先级：{wo.priority or 'MEDIUM'}",
                f"- 维修员：{tech.real_name if tech else '-'}",
            ]
            if wo.location:
                lines.append(f"- 位置：{wo.location}")
            if wo.progress_logs:
                last = wo.progress_logs[-1]
                lines.append(f"- 最新进度：{last.remark or ''}")
            return "\n".join(lines)
        finally:
            db.close()

    def query_my_work_orders(self, staff_id: str) -> str:
        """查询指定钉钉用户名下待处理工单（只读）。"""
        if not staff_id:
            return "缺少用户标识（钉钉企业 userId / senderStaffId）。"
        from app.core.database import SessionLocal
        from app.models.user import User
        from app.models.work_order import WorkOrder, WorkOrderStatus
        active = (
            WorkOrderStatus.SUBMITTED,
            WorkOrderStatus.ASSIGNED,
            WorkOrderStatus.ACCEPTED,
            WorkOrderStatus.ARRIVED,
            WorkOrderStatus.INSPECTING,
            WorkOrderStatus.IN_PROGRESS,
            WorkOrderStatus.ARCHIVING,
            WorkOrderStatus.INTAKE,
            WorkOrderStatus.DIAGNOSING,
            WorkOrderStatus.QUOTING,
            WorkOrderStatus.APPROVED,
            WorkOrderStatus.QC,
        )
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.dingtalk_userid == staff_id).first()
            if not user:
                return "未识别到该系统用户，请先在系统中绑定钉钉账号。"
            wos = (
                db.query(WorkOrder)
                .filter(WorkOrder.technician_id == user.id, WorkOrder.status.in_(active))
                .order_by(WorkOrder.created_at.desc())
                .limit(10)
                .all()
            )
            if not wos:
                return "您名下暂时没有待处理的工单。"
            lines = [f"您名下共有 **{len(wos)}** 个待处理工单：", ""]
            for wo in wos:
                lines.append(
                    f"- {wo.work_order_no}｜{wo.fault_description or '-'}｜{_status_cn(wo.status)}"
                )
            lines.append("")
            lines.append("回复工单号可查看详情。")
            return "\n".join(lines)
        finally:
            db.close()

    # ---------- 写操作入口（具体校验/落库由 API 或 persist 回调执行，避免重复实现状态机） ----------
    def create_work_order(self, work_order_data: Optional[Dict] = None, *, persist=None):
        self.claim_write("create_work_order")
        if persist is not None:
            return persist(work_order_data or {})
        return {"accepted": True, "action": "create_work_order", "data": work_order_data or {}}

    def transition_status(self, work_order_id: Any = None, *, persist=None, **kwargs):
        self.claim_write("transition_status")
        if persist is not None:
            return persist()
        return {"accepted": True, "action": "transition_status", "work_order_id": work_order_id, **kwargs}

    def approve_work_order(self, work_order_id: Any = None, *, persist=None, **kwargs):
        self.claim_write("approve_work_order")
        if persist is not None:
            return persist()
        return {"accepted": True, "action": "approve_work_order", "work_order_id": work_order_id, **kwargs}

    def complete_work_order(self, work_order_data: Optional[Dict] = None, *, persist=None):
        """完工入口：可先做理解/沉淀，再由 persist 执行状态变更与扣料。"""
        self.claim_write("complete_work_order")
        analysis = None
        extracted = None
        if work_order_data:
            try:
                analysis = self.analyze_ticket(work_order_data)
            except Exception:
                analysis = None
        if persist is not None:
            return persist(analysis)
        return {
            "accepted": True,
            "action": "complete_work_order",
            "analysis": analysis,
            "extracted": extracted,
            "data": work_order_data or {},
        }

    def deduct_spare_parts(self, *, persist=None, **kwargs):
        self.claim_write("deduct_spare_parts")
        if persist is not None:
            return persist()
        return {"accepted": True, "action": "deduct_spare_parts", **kwargs}


work_order_agent = WorkOrderAgent()
