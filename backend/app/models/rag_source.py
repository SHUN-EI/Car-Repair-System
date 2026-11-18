"""多源 RAG 来源登记：每一批入库数据的种类、版本、原文件和发布状态。"""

from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from app.models.base import BaseModel


class RagSource(BaseModel):
    """一条来源登记。source_kind 区分原厂手册、技术手册、工单、聊天、OBD、图谱等；status 为 DRAFT / PUBLISHED / DEPRECATED。"""
    __tablename__ = "rag_sources"

    source_kind = Column(String(40), nullable=False, index=True, comment="OEM_MANUAL / TECH_MANUAL / WORK_ORDER / HISTORICAL_WO / CHAT / OBD / GRAPH")
    title = Column(String(300), nullable=False, comment="来源标题，如手册名或码表名")
    publisher = Column(String(200), comment="出版社或厂商")
    version = Column(String(80), comment="版本号")
    applicability = Column(JSONB, comment="适用车型等，如 {make, model, year_from, year_to}")
    file_uri = Column(Text, comment="原文件路径或 URI，手册需保留原件")
    checksum = Column(String(64), comment="原文件校验和")
    copyright_note = Column(Text, comment="版权说明；原厂手册仅限门店内检索")
    status = Column(String(20), nullable=False, default="DRAFT", comment="DRAFT / PUBLISHED / DEPRECATED")
    ingested_at = Column(DateTime, comment="完成入库的时间")

    def __repr__(self):
        """调试时输出主键、种类和标题。"""
        return f"<RagSource(id={self.id}, kind={self.source_kind}, title={self.title!r})>"
