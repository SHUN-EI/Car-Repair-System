"""数据模型汇总入口：把各业务表的 SQLAlchemy 模型集中导出，供接口、领域层和脚本统一 import。

具体表结构和字段说明写在各自模块里；本文件只做重新导出，不定义新表。
"""

from app.models.device import Device
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.models.knowledge import KnowledgeItem, KnowledgeStatus
from app.models.user import User, UserRole
from app.models.spare_part import SparePart
from app.models.category import Category
from app.models.fault_code import FaultCodeMapping
from app.models.fault_phenomenon_category import FaultPhenomenonCategory
from app.models.root_cause_category import RootCauseCategory
from app.models.progress_log import WorkOrderProgressLog
from app.models.duty_schedule import DutySchedule, ShiftType
from app.models.leave_request import (
    LeaveRequest, LeaveRequestDetail,
    LeaveType, LeaveRequestStatus, LeaveShift,
)
from app.models.sys_config import SysConfig
from app.models.notification import Notification
from app.models.manual_code import ManualCodeEntry
from app.models.customer import Customer
from app.models.store import Store, Bay
from app.models.vehicle import Vehicle
from app.models.appointment import Appointment
from app.models.part_sku import PartSku
from app.models.service_catalog import ServicePackage, ServiceSku
from app.models.quote import Quote, QuoteLine
from app.models.payment import PaymentIntent
from app.models.follow_up import FollowUpReminder
from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.models.stock import StockMovement, StorePartStock
from app.models.rag_source import RagSource
from app.models.obd_code import ObdCode
from app.models.repair_manual import RepairManual, RepairManualChunk
from app.models.knowledge_graph import KgEntity, KgRelation
from app.models.consult_faq import ConsultConversation, ConsultMessage, ConsultFaq

__all__ = [
    "Device", "WorkOrder", "WorkOrderStatus",
    "KnowledgeItem", "KnowledgeStatus",
    "User", "UserRole",
    "SparePart",
    "Category",
    "FaultCodeMapping",
    "FaultPhenomenonCategory",
    "RootCauseCategory",
    "WorkOrderProgressLog",
    "DutySchedule", "ShiftType",
    "LeaveRequest", "LeaveRequestDetail",
    "LeaveType", "LeaveRequestStatus", "LeaveShift",
    "SysConfig",
    "Notification",
    "ManualCodeEntry",
    "Customer",
    "Store", "Bay",
    "Vehicle",
    "Appointment",
    "PartSku",
    "ServicePackage", "ServiceSku",
    "Quote", "QuoteLine",
    "PaymentIntent",
    "FollowUpReminder",
    "PurchaseOrder", "PurchaseOrderLine",
    "StockMovement", "StorePartStock",
    "RagSource",
    "ObdCode",
    "RepairManual", "RepairManualChunk",
    "KgEntity", "KgRelation",
    "ConsultConversation", "ConsultMessage", "ConsultFaq",
]