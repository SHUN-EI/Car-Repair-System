"""原厂 / 技术手册及其章节切片。全文按章节页码切分，错误码章节仍写入 manual_code_entries。"""

from sqlalchemy import Column, String, Text, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.models.base import BaseModel
from app.core.config import settings


class RepairManual(BaseModel):
    """一本维修手册的登记：厂牌、车型、年款、类型和原文件。"""
    __tablename__ = "repair_manuals"

    source_id = Column(Integer, ForeignKey("rag_sources.id"), nullable=True)
    name = Column(String(300), nullable=False, comment="手册名称")
    manual_type = Column(String(20), nullable=False, default="OEM", comment="OEM 原厂手册 / TECH 技术手册")
    make = Column(String(100), comment="厂牌")
    model = Column(String(100), comment="车型")
    year_from = Column(Integer, comment="适用起始年款")
    year_to = Column(Integer, comment="适用结束年款")
    language = Column(String(20), default="zh")
    version = Column(String(80))
    file_uri = Column(Text, comment="原文件路径，备查")
    copyright_note = Column(Text)
    status = Column(String(20), nullable=False, default="DRAFT", comment="DRAFT / PUBLISHED / DEPRECATED")

    chunks = relationship("RepairManualChunk", back_populates="manual")

    def __repr__(self):
        """调试时输出主键、类型和名称。"""
        return f"<RepairManual(id={self.id}, type={self.manual_type}, name={self.name!r})>"


class RepairManualChunk(BaseModel):
    """手册中的一个章节切片，写入向量和关键词列后供检索引用。"""
    __tablename__ = "repair_manual_chunks"

    manual_id = Column(Integer, ForeignKey("repair_manuals.id"), nullable=False, index=True)
    chapter = Column(String(200), comment="章节，如 第 5 章 制动系统")
    section = Column(String(200), comment="小节标题")
    page_from = Column(String(50))
    page_to = Column(String(50))
    chunk_type = Column(String(40), comment="procedure / spec / wiring / maintenance / general")
    title = Column(String(300), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="DRAFT")
    embedding = Column(Vector(dim=settings.VECTOR_DIM), nullable=True)
    search_tsv = Column(TSVECTOR, nullable=True)
    point_id = Column(String(100), unique=True, index=True, comment="稳定点号 pg:c:{id}")

    manual = relationship("RepairManual", back_populates="chunks")

    def __repr__(self):
        """调试时输出主键、手册编号和标题。"""
        return f"<RepairManualChunk(id={self.id}, manual_id={self.manual_id}, title={self.title!r})>"
