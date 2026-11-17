"""维修知识条目：可由工单提取或人工录入，发布后写入向量库供检索引用。"""

from sqlalchemy import Column, String, Text, Integer, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from pgvector.sqlalchemy import Vector
from app.models.base import BaseModel
from app.core.config import settings
import enum


class KnowledgeStatus(str, enum.Enum):
    """知识生命周期：草案 DRAFT、待审 UNDER_REVIEW、已发布 PUBLISHED、已废弃 DEPRECATED、已归档 ARCHIVED。"""
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


class KnowledgeItem(BaseModel):
    """一条维修知识。embedding 是 bge-m3 向量；search_tsv 是关键词检索列；milvus_id 现为稳定点号（pg:k:{id}），兼容旧接口；source_type/source_id 追溯来源工单；extraction_meta 保存去重分数等提取过程信息。"""
    __tablename__ = "knowledge_items"

    milvus_id = Column(String(100), unique=True, index=True)  # 兼容字段：现为 pg:k:{id}，不再指向 Milvus
    embedding = Column(Vector(dim=settings.VECTOR_DIM), nullable=True)
    search_tsv = Column(TSVECTOR, nullable=True)
    title = Column(String(300), nullable=False)
    content = Column(Text, nullable=False)
    device_type = Column(String(100))
    fault_code = Column(Text, comment="故障码，多个用逗号分隔")
    fault_tags = Column(JSONB)
    source_type = Column(String(20))
    source_id = Column(Integer)
    status = Column(SQLEnum(KnowledgeStatus), default=KnowledgeStatus.DRAFT, nullable=False)
    version = Column(Integer, default=1)
    review_comment = Column(Text, nullable=True, comment="审核备注（驳回原因/修改建议）")
    extraction_meta = Column(JSONB, nullable=True, comment="提取元数据（去重分数/关联工单/关联知识等）")

    def __repr__(self):
        """调试时输出知识主键、标题和当前状态。"""
        return f"<KnowledgeItem(id={self.id}, title='{self.title}', status='{self.status}')>"