"""OBD 标准故障码库：SAE 风格的 P/C/B/U 定义，与手册错误码、工单内部对照表分开。"""

from sqlalchemy import Column, String, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import TSVECTOR
from pgvector.sqlalchemy import Vector
from app.models.base import BaseModel
from app.core.config import settings


class ObdCode(BaseModel):
    """一条 OBD 标准码。code 唯一，如 P0300；embedding / search_tsv 供精确与语义检索。"""
    __tablename__ = "obd_codes"

    code = Column(String(20), unique=True, nullable=False, index=True, comment="标准码，如 P0300")
    system = Column(String(1), comment="P/C/B/U 系统分类")
    title = Column(String(300), nullable=False, comment="中文短标题，如 多缸随机失火")
    description_zh = Column(Text, nullable=False, comment="中文含义")
    description_en = Column(Text, comment="英文含义")
    typical_causes = Column(Text, comment="常见原因")
    typical_steps = Column(Text, comment="常规排查步骤")
    standard = Column(String(80), default="SAE J2012", comment="标准出处")
    source_id = Column(Integer, ForeignKey("rag_sources.id"), nullable=True, comment="来源登记")
    status = Column(String(20), nullable=False, default="PUBLISHED", comment="DRAFT / PUBLISHED / DEPRECATED")
    embedding = Column(Vector(dim=settings.VECTOR_DIM), nullable=True, comment="bge-m3 1024 维向量")
    search_tsv = Column(TSVECTOR, nullable=True)
    point_id = Column(String(100), unique=True, index=True, comment="稳定点号 pg:o:{id}")

    def __repr__(self):
        """调试时输出主键和标准码。"""
        return f"<ObdCode(id={self.id}, code={self.code!r})>"
