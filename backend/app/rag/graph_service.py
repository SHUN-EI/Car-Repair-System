"""PostgreSQL 图谱的查找与一跳扩展。

表不存在或查询失败时返回空结果并记日志，不打断现有四路检索。
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from loguru import logger
from sqlalchemy.orm import Session


def load_alias_pairs(db: Session) -> List[Tuple[str, str]]:
    """读出实体上的别名对，供问句解析补充规范名。失败时返回空列表。"""
    try:
        from app.models.knowledge_graph import KgEntity
        rows = db.query(KgEntity).all()
    except Exception as exc:
        logger.warning(f"[Graph] 读取实体别名失败，跳过图谱扩展: {exc}")
        return []
    pairs: List[Tuple[str, str]] = []
    for row in rows:
        pairs.append((row.name, row.canonical_key))
        pairs.append((row.canonical_key, row.canonical_key))
        for alias in (row.aliases or []):
            if alias:
                pairs.append((str(alias), row.canonical_key))
    return pairs


def _find_entities(db: Session, canonical_keys: Sequence[str]):
    """按规范名、名称或故障码名称找到实体。"""
    from app.models.knowledge_graph import KgEntity
    keys = [k for k in canonical_keys if k]
    if not keys:
        return []
    rows = db.query(KgEntity).all()
    wanted = set(keys)
    matched = []
    for row in rows:
        aliases = set(row.aliases or [])
        aliases.update({row.name, row.canonical_key})
        if wanted & aliases:
            matched.append(row)
    return matched


def expand_one_hop(
    db: Session,
    canonical_keys: Sequence[str],
) -> Dict:
    """按规范名找到实体，再取一跳邻居，并收集关系上的来源编号。

    Returns:
        entities: 命中的起点实体摘要
        neighbors: 一跳邻居摘要
        source_refs: 关系上来源，如 [{"kind": "OEM_MANUAL", "ref": "chunk:1"}]
    """
    empty = {"entities": [], "neighbors": [], "source_refs": []}
    keys = [k for k in canonical_keys if k]
    if not keys:
        return empty
    try:
        from app.models.knowledge_graph import KgEntity, KgRelation
        starts = _find_entities(db, keys)
        if not starts:
            return empty
        start_ids = {row.id for row in starts}
        relations = db.query(KgRelation).filter(
            (KgRelation.subject_id.in_(start_ids)) | (KgRelation.object_id.in_(start_ids))
        ).all()
        neighbor_ids = set()
        source_refs = []
        seen_refs = set()
        for rel in relations:
            other = rel.object_id if rel.subject_id in start_ids else rel.subject_id
            neighbor_ids.add(other)
            key = (rel.source_kind, rel.source_ref)
            if key not in seen_refs:
                seen_refs.add(key)
                source_refs.append({"kind": rel.source_kind, "ref": rel.source_ref})
        neighbors = []
        if neighbor_ids:
            neighbors = db.query(KgEntity).filter(KgEntity.id.in_(neighbor_ids)).all()

        def _brief(row) -> dict:
            return {
                "id": row.id,
                "entity_type": row.entity_type,
                "name": row.name,
                "canonical_key": row.canonical_key,
            }

        return {
            "entities": [_brief(r) for r in starts],
            "neighbors": [_brief(r) for r in neighbors],
            "source_refs": source_refs,
        }
    except Exception as exc:
        logger.warning(f"[Graph] 一跳扩展失败，继续走混合检索: {exc}")
        return empty
