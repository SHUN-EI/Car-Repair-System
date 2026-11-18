"""咨询会话持久化，以及审核后才可检索的客服知识。原始聊天默认不进 retrieve_hybrid。"""

from sqlalchemy import Column, String, Text, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.models.base import BaseModel
from app.core.config import settings


class ConsultConversation(BaseModel):
    """一次咨询或客服会话的头信息，按门店隔离。"""
    __tablename__ = "consult_conversations"

    channel = Column(String(40), nullable=False, comment="pc_consult / dingtalk / owner_h5 等")
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True, index=True)
    staff_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), nullable=False, default="OPEN", comment="OPEN / CLOSED")

    messages = relationship("ConsultMessage", back_populates="conversation")

    def __repr__(self):
        """调试时输出主键和渠道。"""
        return f"<ConsultConversation(id={self.id}, channel={self.channel})>"


class ConsultMessage(BaseModel):
    """会话中的一条已脱敏消息。仅用于本会话上下文或质检，不默认进入混合检索。"""
    __tablename__ = "consult_messages"

    conversation_id = Column(Integer, ForeignKey("consult_conversations.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False, comment="user / assistant / staff")
    content = Column(Text, nullable=False, comment="脱敏后的正文")

    conversation = relationship("ConsultConversation", back_populates="messages")

    def __repr__(self):
        """调试时输出主键、会话编号和角色。"""
        return f"<ConsultMessage(id={self.id}, conversation_id={self.conversation_id}, role={self.role})>"


class ConsultFaq(BaseModel):
    """从对话中抽取、审核通过后的可检索客服知识。"""
    __tablename__ = "consult_faqs"

    title = Column(String(300), nullable=False)
    content = Column(Text, nullable=False)
    source_conversation_id = Column(Integer, ForeignKey("consult_conversations.id"), nullable=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True)
    status = Column(String(20), nullable=False, default="DRAFT", comment="DRAFT / PUBLISHED / DEPRECATED")
    embedding = Column(Vector(dim=settings.VECTOR_DIM), nullable=True)
    search_tsv = Column(TSVECTOR, nullable=True)
    point_id = Column(String(100), unique=True, index=True, comment="稳定点号 pg:f:{id}")

    def __repr__(self):
        """调试时输出主键、状态和标题。"""
        return f"<ConsultFaq(id={self.id}, status={self.status}, title={self.title!r})>"
