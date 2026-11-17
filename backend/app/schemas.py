"""接口层使用的 Pydantic 模型：创建/更新请求、详情响应和通用分页包装。

这些类只负责字段校验与序列化，不含权限、状态机或定价规则；业务判断仍在 domain 与 API 依赖里完成。
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any, Generic, TypeVar
from datetime import date, datetime

T = TypeVar("T")


# ==================== 设备 ====================
class DeviceCreate(BaseModel):
    """创建设备台账的请求体。device_code 必填且需唯一；监控相关字段可选，用于接入外部系统的初始状态。"""
    device_code: str = Field(..., max_length=50)
    device_name: str = Field(..., max_length=200)
    device_type: Optional[str] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    location: Optional[str] = None
    purchase_date: Optional[date] = None
    warranty_expiry: Optional[date] = None
    remark: Optional[str] = None
    run_status: Optional[str] = "UNKNOWN"
    fault_tags: Optional[list] = None
    ext_system_id: Optional[str] = None
    status_source: Optional[str] = None
    status_reason: Optional[str] = None
    monitor_extra: Optional[dict] = None


class DeviceUpdate(BaseModel):
    """更新设备台账的请求体，字段均可选，只更新传入的项。可同步运行状态、心跳和外部监控附加信息。"""
    device_name: Optional[str] = None
    device_type: Optional[str] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    location: Optional[str] = None
    purchase_date: Optional[date] = None
    warranty_expiry: Optional[date] = None
    remark: Optional[str] = None
    run_status: Optional[str] = None
    last_heartbeat: Optional[datetime] = None
    fault_tags: Optional[list] = None
    ext_system_id: Optional[str] = None
    status_source: Optional[str] = None
    status_reason: Optional[str] = None
    last_sync_time: Optional[datetime] = None
    monitor_extra: Optional[dict] = None


class DeviceResponse(BaseModel):
    """设备详情响应，包含主数据、监控状态和时间戳。"""
    id: int
    device_code: str
    device_name: str
    device_type: Optional[str]
    model: Optional[str]
    manufacturer: Optional[str]
    location: Optional[str]
    purchase_date: Optional[date]
    warranty_expiry: Optional[date]
    remark: Optional[str]
    run_status: Optional[str] = "UNKNOWN"
    last_heartbeat: Optional[datetime] = None
    fault_tags: Optional[list] = None
    ext_system_id: Optional[str] = None
    status_source: Optional[str] = None
    status_reason: Optional[str] = None
    last_sync_time: Optional[datetime] = None
    monitor_extra: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ==================== 工单 ====================
class WorkOrderCreate(BaseModel):
    """创建或保存工单时的请求体。可写工单号、设备/车辆/客户、故障现象与方案、附件和派工相关字段；真正的状态变更要走流转接口，不能靠这份请求直接跳到结束态。"""
    work_order_no: Optional[str] = Field(None, max_length=50)
    device_id: Optional[int] = None
    device_code: Optional[str] = None
    fault_code: Optional[str] = None
    device_error_code: Optional[str] = None
    log_text: Optional[str] = None
    fault_description: str
    fault_category: Optional[str] = None
    fault_phenomenon_type: Optional[str] = None
    fault_phenomenon: Optional[str] = None
    fault_media: Optional[List[str]] = None
    attachments: Optional[List[dict]] = None
    root_cause_category: Optional[str] = None
    root_cause_type: Optional[str] = None
    root_cause: Optional[str] = None
    solution_steps: Optional[str] = None
    solution_ref_knowledge_id: Optional[int] = None
    repair_result: Optional[str] = None
    follow_up_plan: Optional[str] = None
    work_hours: Optional[float] = None
    used_parts: Optional[List[dict]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    technician_id: Optional[int] = None
    assignee_id: Optional[int] = None
    reporter_id: Optional[int] = None
    priority: Optional[str] = "MEDIUM"
    location: Optional[str] = None
    status: Optional[str] = "DRAFT"
    tags: Optional[List[str]] = None
    created_by: Optional[int] = None
    vehicle_id: Optional[int] = None
    customer_id: Optional[int] = None
    store_id: Optional[int] = None
    bay_id: Optional[int] = None
    appointment_id: Optional[int] = None


class WorkOrderUpdate(BaseModel):
    """更新工单内容的请求体，字段均可选。用于补现象、根因、方案、附件和用料等，不代替状态流转。"""
    device_id: Optional[int] = None
    device_code: Optional[str] = None
    fault_code: Optional[str] = None
    device_error_code: Optional[str] = None
    log_text: Optional[str] = None
    fault_description: Optional[str] = None
    fault_category: Optional[str] = None
    fault_phenomenon_type: Optional[str] = None
    fault_phenomenon: Optional[str] = None
    fault_media: Optional[List[str]] = None
    attachments: Optional[List[dict]] = None
    root_cause_category: Optional[str] = None
    root_cause_type: Optional[str] = None
    root_cause: Optional[str] = None
    solution_steps: Optional[str] = None
    solution_ref_knowledge_id: Optional[int] = None
    repair_result: Optional[str] = None
    follow_up_plan: Optional[str] = None
    work_hours: Optional[float] = None
    used_parts: Optional[List[dict]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    technician_id: Optional[int] = None
    assignee_id: Optional[int] = None
    priority: Optional[str] = None
    location: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None
    vehicle_id: Optional[int] = None
    customer_id: Optional[int] = None
    store_id: Optional[int] = None
    bay_id: Optional[int] = None
    appointment_id: Optional[int] = None


class WorkOrderResponse(BaseModel):
    """工单详情响应。除表内字段外，还会带上车牌、维修员姓名、开单人工号、可流转的下一状态，以及进度日志列表。"""
    id: int
    work_order_no: str
    device_id: Optional[int]
    device_code: Optional[str] = None
    device_type: Optional[str] = None
    device_name: Optional[str] = None
    fault_code: Optional[str]
    device_error_code: Optional[str] = None
    fault_description: str
    fault_category: Optional[str] = None
    fault_phenomenon_type: Optional[str] = None
    fault_phenomenon: Optional[str]
    fault_media: Optional[Any] = None
    attachments: Optional[Any] = None
    root_cause_category: Optional[str] = None
    root_cause_type: Optional[str] = None
    root_cause: Optional[str]
    solution_steps: Optional[str]
    solution_ref_knowledge_id: Optional[int] = None
    repair_result: Optional[str] = None
    follow_up_plan: Optional[str] = None
    work_hours: Optional[float] = None
    used_parts: Optional[Any]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    technician_id: Optional[int]
    assignee_id: Optional[int] = None
    reporter_id: Optional[int] = None
    priority: Optional[str] = "MEDIUM"
    location: Optional[str] = None
    status: str
    tags: Optional[Any]
    confidence: Optional[float] = None
    analysis_result: Optional[Any] = None
    dispatch_score: Optional[Any] = None
    completion_report: Optional[Any] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[int] = None
    created_by_employee_id: Optional[str] = None
    technician_name: Optional[str] = None
    vehicle_id: Optional[int] = None
    customer_id: Optional[int] = None
    store_id: Optional[int] = None
    bay_id: Optional[int] = None
    appointment_id: Optional[int] = None
    vehicle_plate: Optional[str] = None
    allowed_transitions: List[str] = []
    progress_logs: List["WorkOrderProgressLogResponse"] = []

    model_config = {"from_attributes": True}


class WorkOrderTransition(BaseModel):
    """工单状态流转请求：目标状态、来源渠道（如 WEB/钉钉）、备注、位置和附件。"""
    to_status: str
    source: Optional[str] = "WEB"
    remark: Optional[str] = None
    location: Optional[str] = None
    attachments: Optional[Any] = None


class WorkOrderFromAppointment(BaseModel):
    """预约到店后开接车工单。不走草稿保存时的直接进维修捷径。"""
    appointment_id: int
    fault_description: Optional[str] = None
    technician_id: Optional[int] = None
    bay_id: Optional[int] = None


class WorkOrderDispatchCreate(BaseModel):
    """主管派工开单请求：至少要能定位设备和故障描述，并指定维修员、优先级和位置等派工信息。"""
    device_id: Optional[int] = None
    device_code: Optional[str] = None
    fault_code: Optional[str] = None
    fault_description: str
    fault_media: Optional[List[str]] = None
    priority: Optional[str] = "MEDIUM"
    location: Optional[str] = None
    technician_id: int
    tags: Optional[List[str]] = None
    fault_category: Optional[str] = None
    fault_phenomenon_type: Optional[str] = None
    fault_phenomenon: Optional[str] = None


class WorkOrderProgressLogResponse(BaseModel):
    """一条工单进度日志的响应，包含流转两端状态、操作人、来源和附件。"""
    id: int
    work_order_id: int
    from_status: Optional[str] = None
    to_status: str
    operator_id: Optional[int] = None
    operator_name: Optional[str] = None
    source: str
    remark: Optional[str] = None
    location: Optional[str] = None
    attachments: Optional[Any] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ==================== 工单分析与审核 ====================
class TicketAnalysisResponse(BaseModel):
    """工单 AI 分析响应"""
    work_order_id: int
    # 标准化字段
    standardized_fault_code: Optional[str] = None
    standardized_fault_phenomenon: Optional[str] = None
    standardized_root_cause: Optional[str] = None
    standardized_solution_steps: Optional[str] = None
    # 分类字段
    device_type: Optional[str] = None
    fault_category: Optional[str] = None
    tags: List[str] = []
    severity: Optional[str] = None
    # 校验
    completeness_score: float = 0.0
    missing_fields: List[str] = []
    validation_notes: str = ""
    # 综合
    confidence: float = 0.0
    raw_reasoning: str = ""
    suggested_actions: List[str] = []
    # 库存关联
    inventory: Optional[dict] = None


class WorkOrderReviewRequest(BaseModel):
    """工单审核请求"""
    action: str = Field(..., pattern="^(approve|reject)$")
    comment: Optional[str] = None


class WorkOrderReviewResponse(BaseModel):
    """工单审核响应"""
    work_order_id: int
    new_status: str
    action: str
    comment: Optional[str] = None


# ==================== 知识条目 ====================
class KnowledgeCreate(BaseModel):
    """新建知识条目的请求体。可指定标题、正文、设备类型、故障码、标签和来源，默认进入草案或指定状态。"""
    title: str = Field(..., max_length=300)
    content: str
    device_type: Optional[str] = None
    fault_code: Optional[str] = None
    fault_tags: Optional[List[str]] = None
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    status: Optional[str] = "DRAFT"


class KnowledgeUpdate(BaseModel):
    """更新知识条目的请求体，字段均可选，用于改内容和状态。发布/废弃另有带角色校验的专用接口。"""
    title: Optional[str] = None
    content: Optional[str] = None
    device_type: Optional[str] = None
    fault_code: Optional[str] = None
    fault_tags: Optional[List[str]] = None
    status: Optional[str] = None


class KnowledgeResponse(BaseModel):
    """知识条目详情，含版本、向量库 ID、审核意见和提取元数据。"""
    id: int
    title: str
    content: str
    device_type: Optional[str]
    fault_code: Optional[str]
    fault_tags: Optional[Any]
    source_type: Optional[str]
    source_id: Optional[int]
    status: str
    version: int
    milvus_id: Optional[str]
    review_comment: Optional[str] = None
    extraction_meta: Optional[Any] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ==================== 知识提取与审核 ====================
class KnowledgeExtractRequest(BaseModel):
    """从工单提取知识条目请求"""
    work_order_id: int


class KnowledgeDedupResult(BaseModel):
    """去重检测结果"""
    has_duplicate: bool = False
    similarity_score: float = 0.0
    matched_items: List[dict] = []


class KnowledgeExtractResponse(BaseModel):
    """知识提取响应"""
    extracted: dict  # 提取的知识内容
    dedup: KnowledgeDedupResult  # 去重检测结果
    knowledge_id: Optional[int] = None  # 如果自动创建了知识条目
    auto_created: bool = False  # 是否自动创建（无重复时）


class KnowledgeReviewRequest(BaseModel):
    """知识审核请求"""
    action: str = Field(..., pattern="^(submit|publish|reject|deprecate)$")
    comment: Optional[str] = None


class KnowledgeReviewResponse(BaseModel):
    """知识审核响应"""
    knowledge_id: int
    new_status: str
    action: str
    comment: Optional[str] = None


# ==================== 备件 ====================
class FitmentRule(BaseModel):
    """备件适配一条。空字段表示这一维不限制。"""
    brand: Optional[str] = Field(None, max_length=50)
    series: Optional[str] = Field(None, max_length=80)
    year_from: Optional[int] = Field(None, ge=1900, le=2100)
    year_to: Optional[int] = Field(None, ge=1900, le=2100)
    engine: Optional[str] = Field(None, max_length=50)


class SparePartCreate(BaseModel):
    """新增配件库存的请求体。part_code 必填且唯一；可带安全库存、单价、适配规则 fitment 和所属门店。"""
    part_code: str = Field(..., max_length=50)
    part_name: str = Field(..., max_length=200)
    specification: Optional[str] = None
    unit: Optional[str] = "个"
    stock_quantity: Optional[int] = 0
    safety_stock: Optional[int] = 0
    unit_price: Optional[float] = 0.0
    device_type: Optional[str] = None
    location: Optional[str] = None
    supplier: Optional[str] = None
    sku_id: Optional[int] = None
    fitment: Optional[List[FitmentRule]] = None
    store_id: Optional[int] = None


class SparePartUpdate(BaseModel):
    """更新配件主数据的请求体，字段均可选。库存数量的业务增减应走出入库，而不是只改这个字段。"""
    part_name: Optional[str] = None
    specification: Optional[str] = None
    unit: Optional[str] = None
    stock_quantity: Optional[int] = None
    safety_stock: Optional[int] = None
    unit_price: Optional[float] = None
    device_type: Optional[str] = None
    location: Optional[str] = None
    supplier: Optional[str] = None
    sku_id: Optional[int] = None
    fitment: Optional[List[FitmentRule]] = None


class SparePartResponse(BaseModel):
    """配件详情响应。除总库存外，可能带上门店结存 store_on_hand 和适配规则。"""
    id: int
    part_code: str
    part_name: str
    specification: Optional[str]
    unit: Optional[str]
    stock_quantity: int
    safety_stock: int
    unit_price: float
    device_type: Optional[str]
    location: Optional[str]
    supplier: Optional[str]
    sku_id: Optional[int] = None
    fitment: Optional[List[FitmentRule]] = None
    store_id: Optional[int] = None
    store_on_hand: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ==================== 用户 ====================
class UserCreate(BaseModel):
    """创建系统用户的请求体。用户名和密码必填，可指定角色和所属门店、工号与联系方式。"""
    username: str = Field(..., max_length=50)
    employee_id: Optional[str] = Field(None, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)
    real_name: str = Field(..., max_length=100)
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = "TECHNICIAN"
    store_id: Optional[int] = None


class UserUpdate(BaseModel):
    """更新用户资料的请求体，字段均可选。可用于改角色、启用状态、部门和门店绑定；一般不在这里改密码。"""
    employee_id: Optional[str] = None
    real_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    department: Optional[str] = None
    title: Optional[str] = None
    store_id: Optional[int] = None


class UserResponse(BaseModel):
    """用户详情响应。包含角色、门店和联系方式，不返回密码哈希。"""
    id: int
    username: str
    employee_id: Optional[str] = None
    real_name: str
    email: Optional[str]
    phone: Optional[str]
    role: str
    is_active: bool
    store_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ==================== 分类树 ====================
class CategoryCreate(BaseModel):
    """创建分类节点的请求体。可指定父节点、类型、排序和说明，用于设备或故障等分类树。"""
    name: str = Field(..., max_length=100)
    code: str = Field(..., max_length=50)
    parent_id: Optional[int] = None
    category_type: str = Field(..., max_length=30)
    sort_order: Optional[int] = 0
    description: Optional[str] = None


class CategoryUpdate(BaseModel):
    """更新分类节点的请求体，字段均可选。"""
    name: Optional[str] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None
    description: Optional[str] = None


class CategoryResponse(BaseModel):
    """分类节点响应，可带子节点列表，便于一次性返回树形结构。"""
    id: int
    name: str
    code: str
    parent_id: Optional[int]
    category_type: str
    sort_order: int
    description: Optional[str]
    children: List["CategoryResponse"] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ==================== 排班/请假 ====================
class DutyScheduleCreate(BaseModel):
    """创建一条排班记录：日期、班次、人员，以及排班类型、备注或请假相关字段。"""
    date: date
    shift: Optional[str] = "ALL_DAY"
    user_id: int
    schedule_type: Optional[str] = "MANUAL"
    note: Optional[str] = None
    leave_type: Optional[str] = None
    leave_status: Optional[str] = 'APPROVED'


class DutyScheduleResponse(BaseModel):
    """排班记录响应，若由请假生成会带上来源请假单和替班对象。"""
    id: int
    date: date
    shift: str
    user_id: int
    schedule_type: str
    note: Optional[str]
    leave_type: Optional[str]
    leave_status: str
    source_leave_request_id: Optional[int] = None
    source_substitute_for_id: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# =============================================================
# 请假申请单 (Phase 2.1)
# =============================================================
class LeaveRequestDetailCreate(BaseModel):
    """单日单班次请假单元，由后端按区间拆单落库；外部可直接传明细或传 from_date+to_date 由后端拆"""
    leave_date: date
    leave_shift: str = "ALL_DAY"


class LeaveRequestSubmit(BaseModel):
    """维修师傅提交请假申请（钉钉卡片回调或网页端表单）"""
    requester_id: Optional[int] = None  # 如不传，取 current_user.id
    leave_type: str = "ANNUAL"
    leave_reason: Optional[str] = None
    # 方式一：按日期区间 + 统一班次（常用）
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    shift_of_range: Optional[str] = "ALL_DAY"
    # 方式二：显式传拆单明细（跨多天、班次不一的复杂情况）
    details: Optional[List[LeaveRequestDetailCreate]] = None
    # 幂等/关联ID
    correlation_id: str  # 调用方必须传（钉钉 outTrackId / 前端 UUID）
    # 备注
    note: Optional[str] = None


class LeaveRequestApprove(BaseModel):
    """主管批准"""
    substitute_user_id: Optional[int] = None   # 人数不足时强制指定顶岗人
    approver_comment: Optional[str] = None


class LeaveRequestReject(BaseModel):
    """主管拒绝"""
    approver_comment: str = Field(..., min_length=2, max_length=500, description="拒绝理由（必填）")


class LeaveRequestQuery(BaseModel):
    """列表查询过滤条件"""
    status: Optional[str] = None        # PENDING / APPROVED / REJECTED / CANCELLED
    requester_id: Optional[int] = None
    approver_id: Optional[int] = None
    date_from: Optional[date] = None    # 与请假明细日期交叠过滤
    date_to: Optional[date] = None
    leave_type: Optional[str] = None


class LeaveRequestDetailResponse(BaseModel):
    """请假单中按天拆分的一条明细：具体日期和班次。"""
    id: int
    leave_request_id: int
    leave_date: date
    leave_shift: str

    model_config = {"from_attributes": True}


class LeaveRequestResponse(BaseModel):
    """请假单详情，含申请人、审批人、替班人、明细，以及批准后是否在岗、是否还有未完成工单等展示字段。"""
    id: int
    requester_id: int
    requester_name: str
    leave_type: str
    leave_reason: Optional[str]
    status: str
    approver_id: Optional[int] = None
    approver_name: Optional[str] = None
    approver_comment: Optional[str] = None
    substitute_user_id: Optional[int] = None
    substitute_name: Optional[str] = None
    correlation_id: Optional[str] = None
    submitted_at: Optional[datetime] = None
    handled_at: Optional[datetime] = None
    details: List[LeaveRequestDetailResponse] = []
    created_at: datetime
    updated_at: datetime
    # 辅助计算属性
    on_duty_after: Optional[dict] = None  # {date: remaining_count} 审批通过后每天剩余值班人数
    pending_work_orders: Optional[List[dict]] = None  # 审批时返回未完成工单冲突警告

    model_config = {"from_attributes": True}


# ==================== Phase 0 汽修域骨架 ====================
class CustomerCreate(BaseModel):
    """创建客户档案的请求体。可关联系统用户 user_id，供车主账号自动或人工建档。"""
    name: str = Field(..., max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = None
    id_no: Optional[str] = Field(None, max_length=30)
    remark: Optional[str] = None
    user_id: Optional[int] = None


class CustomerUpdate(BaseModel):
    """更新客户档案的请求体，字段均可选。"""
    name: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = None
    id_no: Optional[str] = Field(None, max_length=30)
    remark: Optional[str] = None
    user_id: Optional[int] = None


class CustomerResponse(BaseModel):
    """客户档案详情响应。"""
    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    id_no: Optional[str] = None
    remark: Optional[str] = None
    user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StoreCreate(BaseModel):
    """创建门店的请求体。编码、名称必填，可带地址和电话。"""
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=200)
    address: Optional[str] = None
    phone: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = True


class StoreUpdate(BaseModel):
    """更新门店资料的请求体，字段均可选，也可停用门店。"""
    name: Optional[str] = Field(None, max_length=200)
    address: Optional[str] = None
    phone: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None


class StoreResponse(BaseModel):
    """门店详情响应。"""
    id: int
    code: str
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BayCreate(BaseModel):
    """创建工位的请求体，必须归属一家门店。"""
    store_id: int
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    bay_type: Optional[str] = "通用"
    is_active: Optional[bool] = True


class BayUpdate(BaseModel):
    """更新工位的请求体，字段均可选。"""
    code: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=100)
    bay_type: Optional[str] = None
    is_active: Optional[bool] = None


class BayResponse(BaseModel):
    """工位详情响应。"""
    id: int
    store_id: int
    code: str
    name: str
    bay_type: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VehicleCreate(BaseModel):
    """创建车辆档案的请求体。车牌必填，可写 VIN、品牌车系年款和车主客户 ID。"""
    plate: str = Field(..., max_length=20)
    vin: Optional[str] = Field(None, max_length=17)
    make: Optional[str] = Field(None, max_length=50)
    model: Optional[str] = Field(None, max_length=80)
    year: Optional[int] = Field(None, ge=1980, le=2100)
    owner_id: Optional[int] = None


class VehicleUpdate(BaseModel):
    """更新车辆档案的请求体，字段均可选。"""
    plate: Optional[str] = Field(None, max_length=20)
    vin: Optional[str] = Field(None, max_length=17)
    make: Optional[str] = Field(None, max_length=50)
    model: Optional[str] = Field(None, max_length=80)
    year: Optional[int] = Field(None, ge=1980, le=2100)
    owner_id: Optional[int] = None


class VehicleResponse(BaseModel):
    """车辆详情响应，会附带车主姓名 owner_name 便于展示。"""
    id: int
    plate: str
    vin: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AppointmentCreate(BaseModel):
    """创建预约的请求体。必须指定门店和到店时间，工位、客户和车辆可选。"""
    store_id: int
    bay_id: Optional[int] = None
    customer_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    scheduled_at: datetime
    remark: Optional[str] = None


class AppointmentUpdate(BaseModel):
    """更新预约的请求体，字段均可选。改状态时仍应满足预约状态机，不能随意写成任意值。"""
    bay_id: Optional[int] = None
    customer_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    scheduled_at: Optional[datetime] = None
    status: Optional[str] = None
    remark: Optional[str] = None


class AppointmentResponse(BaseModel):
    """预约详情响应，并带上当前状态下允许转入的下一状态。"""
    id: int
    store_id: int
    bay_id: Optional[int] = None
    customer_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    scheduled_at: datetime
    status: str
    remark: Optional[str] = None
    allowed_transitions: List[str] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PartSkuCreate(BaseModel):
    """创建配件目录 SKU 的请求体，含编码、名称、品牌、单位和目录价。"""
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=200)
    brand: Optional[str] = Field(None, max_length=100)
    unit: Optional[str] = "个"
    list_price: Optional[float] = Field(0.0, ge=0)
    cost_price: Optional[float] = Field(0.0, ge=0)
    specification: Optional[str] = None
    is_active: Optional[bool] = True


class PartSkuUpdate(BaseModel):
    """更新配件目录 SKU 的请求体，字段均可选。"""
    name: Optional[str] = Field(None, max_length=200)
    brand: Optional[str] = Field(None, max_length=100)
    unit: Optional[str] = None
    list_price: Optional[float] = Field(None, ge=0)
    cost_price: Optional[float] = Field(None, ge=0)
    specification: Optional[str] = None
    is_active: Optional[bool] = None


class PartSkuResponse(BaseModel):
    """配件目录 SKU 详情响应。"""
    id: int
    code: str
    name: str
    brand: Optional[str] = None
    unit: Optional[str] = None
    list_price: Optional[float] = 0.0
    cost_price: Optional[float] = 0.0
    specification: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ServicePackageCreate(BaseModel):
    """创建保养套餐的请求体。品牌、车系、里程和症状关键词留空表示这一维不限制。"""
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=200)
    description: Optional[str] = None
    brand: Optional[str] = Field(None, max_length=50)
    series: Optional[str] = Field(None, max_length=80)
    mileage_from: Optional[int] = Field(None, ge=0)
    mileage_to: Optional[int] = Field(None, ge=0)
    symptom_keywords: Optional[List[str]] = None
    list_price: Optional[float] = Field(0, ge=0)
    is_active: Optional[bool] = True


class ServicePackageUpdate(BaseModel):
    """更新保养套餐的请求体，字段均可选。"""
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    brand: Optional[str] = Field(None, max_length=50)
    series: Optional[str] = Field(None, max_length=80)
    mileage_from: Optional[int] = Field(None, ge=0)
    mileage_to: Optional[int] = Field(None, ge=0)
    symptom_keywords: Optional[List[str]] = None
    list_price: Optional[float] = Field(None, ge=0)
    is_active: Optional[bool] = None


class ServicePackageResponse(BaseModel):
    """保养套餐详情响应。"""
    id: int
    code: str
    name: str
    description: Optional[str] = None
    brand: Optional[str] = None
    series: Optional[str] = None
    mileage_from: Optional[int] = None
    mileage_to: Optional[int] = None
    symptom_keywords: Optional[List[str]] = None
    list_price: float = 0
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ServiceSkuCreate(BaseModel):
    """创建服务工时项目的请求体。可挂到套餐下，也可单独售卖，并带推荐用的车型和症状条件。"""
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=200)
    labor_minutes: Optional[int] = Field(0, ge=0)
    base_price: Optional[float] = Field(0, ge=0)
    package_id: Optional[int] = None
    category: Optional[str] = Field(None, max_length=50)
    symptom_keywords: Optional[List[str]] = None
    brand: Optional[str] = Field(None, max_length=50)
    series: Optional[str] = Field(None, max_length=80)
    mileage_from: Optional[int] = Field(None, ge=0)
    mileage_to: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = True


class ServiceSkuUpdate(BaseModel):
    """更新服务工时项目的请求体，字段均可选。"""
    name: Optional[str] = Field(None, max_length=200)
    labor_minutes: Optional[int] = Field(None, ge=0)
    base_price: Optional[float] = Field(None, ge=0)
    package_id: Optional[int] = None
    category: Optional[str] = Field(None, max_length=50)
    symptom_keywords: Optional[List[str]] = None
    brand: Optional[str] = Field(None, max_length=50)
    series: Optional[str] = Field(None, max_length=80)
    mileage_from: Optional[int] = Field(None, ge=0)
    mileage_to: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class ServiceSkuResponse(BaseModel):
    """服务工时项目详情响应。"""
    id: int
    code: str
    name: str
    labor_minutes: int = 0
    base_price: float = 0
    package_id: Optional[int] = None
    category: Optional[str] = None
    symptom_keywords: Optional[List[str]] = None
    brand: Optional[str] = None
    series: Optional[str] = None
    mileage_from: Optional[int] = None
    mileage_to: Optional[int] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ServiceRecommendRequest(BaseModel):
    """套餐/项目推荐的查询条件：可用车辆 ID 或车牌，补品牌、车系、里程和症状文本。"""
    vehicle_id: Optional[int] = None
    plate: Optional[str] = None
    brand: Optional[str] = None
    series: Optional[str] = None
    mileage: Optional[int] = Field(None, ge=0, description="公里。不传表示未知里程，不按区间过滤")
    symptoms: Optional[str] = None


class QuoteSuggestionIn(BaseModel):
    """生成报价时传入的一条建议项目：名称、编码、数量、单价、类型和引用 ID，缺省单价时由规则引擎回退目录价。"""
    name: str = Field(..., max_length=200)
    code: Optional[str] = Field(None, max_length=50)
    qty: float = Field(1, gt=0)
    unit_price: Optional[float] = Field(None, ge=0)
    line_type: Optional[str] = None
    ref_id: Optional[int] = None


class QuoteDraftRequest(BaseModel):
    """生成草案报价的请求。可挂工单或车辆，并传入问诊文本、建议项目、里程和症状；开关控制是否纳入已用配件和套餐。"""
    work_order_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    consult_text: Optional[str] = None
    suggestions: Optional[List[QuoteSuggestionIn]] = None
    mileage: Optional[int] = Field(None, ge=0)
    symptoms: Optional[str] = None
    include_packages: bool = False
    include_used_parts: bool = True


class QuoteLineCreate(BaseModel):
    """向草案报价追加一条人工明细的请求。"""
    name: str = Field(..., max_length=200)
    code: Optional[str] = Field(None, max_length=50)
    qty: float = Field(1, gt=0)
    unit_price: float = Field(0, ge=0)
    line_type: Optional[str] = "LABOR"
    ref_id: Optional[int] = None


class QuoteLineResponse(BaseModel):
    """一条报价明细的响应，含行号、类型、数量、单价、金额和来源。"""
    id: int
    line_no: int
    line_type: str
    name: str
    code: Optional[str] = None
    qty: float
    unit_price: float
    amount: float
    source: Optional[str] = None
    ref_id: Optional[int] = None

    model_config = {"from_attributes": True}


class QuoteResponse(BaseModel):
    """报价单详情响应，含状态中文名、客户是否已确认、合计、明细和允许的下一状态。"""
    id: int
    quote_no: str
    work_order_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    customer_id: Optional[int] = None
    store_id: Optional[int] = None
    status: str
    status_label: str = ""
    customer_confirm: bool = False
    total: float = 0
    mileage: Optional[int] = None
    symptoms: Optional[str] = None
    consult_text: Optional[str] = None
    note: Optional[str] = None
    lines: List[QuoteLineResponse] = []
    allowed_transitions: List[str] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QuoteActionResponse(QuoteResponse):
    """报价确认、拒绝或取消等操作后的返回：在报价详情之外多带 notify，说明是否已尝试通知相关人员。"""
    notify: Optional[dict] = None


class CustomerConfirmRequest(BaseModel):
    """客户确认报价的请求。on_behalf 为真表示由店员代为确认，而不是车主本人操作。"""
    on_behalf: bool = False


class PaymentIntentCreate(BaseModel):
    """为指定报价创建支付意向的请求。只生成占位记录，不会调用真实支付渠道。"""
    quote_id: int


class PaymentIntentResponse(BaseModel):
    """支付意向详情。reused 表示是否复用了已有意向，而不是新开一笔。"""
    id: int
    intent_no: str
    quote_id: Optional[int] = None
    work_order_id: Optional[int] = None
    amount: float
    currency: str
    channel: str
    status: str
    status_label: str = ""
    note: Optional[str] = None
    reused: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ==================== 通用 ====================
class PaginatedResponse(BaseModel, Generic[T]):
    """通用分页包装：总数、当前页数据、页码和每页大小。条目类型由泛型参数 T 决定。"""
    total: int
    items: List[T]
    page: int = 1
    page_size: int = 10