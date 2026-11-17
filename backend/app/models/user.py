"""系统用户：登录账号、角色、可选的所属门店，以及钉钉绑定和技师负荷等扩展字段。"""

from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
from datetime import datetime


class UserRole(str, __import__('enum').Enum):
    """用户角色：管理员 ADMIN、维修员 TECHNICIAN、主管 SUPERVISOR、车间工人 WORKER、车主 OWNER。车主走 H5 预约和进度，不按门店角色授权。"""
    ADMIN = "ADMIN"
    TECHNICIAN = "TECHNICIAN"
    SUPERVISOR = "SUPERVISOR"
    WORKER = "WORKER"
    OWNER = "OWNER"  # 车主，H5 预约与进度


class User(BaseModel):
    """登录用户。role 决定接口权限；store_id 绑定门店后，店内角色只能操作本店数据。钉钉相关字段用于免登和推送，current_workload_count 由工单流转维护。"""
    __tablename__ = "users"

    username = Column(String(50), unique=True, nullable=False, index=True)
    employee_id = Column(String(50), unique=True, nullable=True, index=True, comment="工号，唯一")
    password_hash = Column(String(255), nullable=False)
    real_name = Column(String(100), nullable=False)
    email = Column(String(200))
    phone = Column(String(20))
    role = Column(String(20), default=UserRole.TECHNICIAN.value, nullable=False)
    is_active = Column(Boolean, default=True)

    dingtalk_userid = Column(String(100), unique=True, index=True, nullable=True)
    dingtalk_name = Column(String(100), nullable=True, comment="钉钉账号昵称")
    dingtalk_union_id = Column(String(100), nullable=True, index=True, comment="钉钉 unionId（跨应用唯一，机器人识别用）")
    dingtalk_bound_at = Column(DateTime, nullable=True, comment="钉钉账号绑定时间")
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True, comment="所属门店，空表示未绑定")
    department = Column(String(200))
    title = Column(String(100))
    skills = Column(String(500), comment="旧:技能标签(逗号分隔),保留1个月")
    skills_json = Column(JSONB, comment="技能熟练度字典 {类型: 1-5}")
    current_workload_count = Column(Integer, nullable=False, default=0,
                                     server_default="0", comment="当前未完成工单数(冗余)")
    last_online_at = Column(DateTime, nullable=True, comment="最近在线时间")
    last_login_at = Column(DateTime)

    work_orders = relationship("WorkOrder", foreign_keys="WorkOrder.assignee_id")
    duty_schedules = relationship("DutySchedule", back_populates="user",
                                  cascade="all, delete-orphan")

    def __repr__(self):
        """调试时输出用户主键、用户名和角色。"""
        return f"<User(username='{self.username}', role='{self.role}')>"