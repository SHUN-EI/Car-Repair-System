"""PostgreSQL 知识图谱：实体表与关系表，问诊时只做一跳扩展。"""

from sqlalchemy import Column, String, Text, Integer, ForeignKey, Float, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from app.models.base import BaseModel


class KgEntity(BaseModel):
    """图谱中的一个实体。canonical_key 用于合并同义词，如「刹车有点紧」归到「刹车紧」。"""
    __tablename__ = "kg_entities"

    entity_type = Column(String(40), nullable=False, index=True, comment="vehicle_model / system / part / symptom / fault_code / procedure / cause")
    name = Column(String(200), nullable=False, comment="展示名")
    canonical_key = Column(String(200), unique=True, nullable=False, index=True, comment="规范名，唯一")
    aliases = Column(JSONB, default=list, comment="同义表达列表")
    properties = Column(JSONB, default=dict, comment="实体属性")

    def __repr__(self):
        """调试时输出类型和规范名。"""
        return f"<KgEntity(id={self.id}, type={self.entity_type}, key={self.canonical_key!r})>"


class KgRelation(BaseModel):
    """一条有向关系，必须带来源，便于核对和按来源回滚。"""
    __tablename__ = "kg_relations"
    __table_args__ = (
        UniqueConstraint(
            "subject_id", "predicate", "object_id", "source_kind", "source_ref",
            name="uq_kg_relations_triple_source",
        ),
    )

    subject_id = Column(Integer, ForeignKey("kg_entities.id"), nullable=False, index=True)
    predicate = Column(String(80), nullable=False, index=True, comment="applies_to / manifests_as / caused_by / has_code / needs_part / suggests_step")
    object_id = Column(Integer, ForeignKey("kg_entities.id"), nullable=False, index=True)
    properties = Column(JSONB, default=dict)
    source_kind = Column(String(40), nullable=False, comment="OEM_MANUAL / OBD / WORK_ORDER / FAQ 等")
    source_ref = Column(String(80), nullable=False, comment="来源编号，如 chunk:12 / obd:P0300 / knowledge:3")
    confidence = Column(Float, default=1.0)

    def __repr__(self):
        """调试时输出主谓宾和来源。"""
        return f"<KgRelation({self.subject_id} -{self.predicate}-> {self.object_id} src={self.source_ref})>"
