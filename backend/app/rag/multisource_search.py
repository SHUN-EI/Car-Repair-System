"""多源召回：OBD 标准码、手册章节切片、已审客服知识，以及图谱关联条目。

每条结果带 `_dedup_key`（O: / C: / F:）和 `source_type`，交给现有 rrf_merge。
表不存在或推理服务不可用时返回空列表，不抛给调用方。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.rag.lexical import build_or_tsquery, cosine_distance_to_similarity, tokenize_repair_text


def obd_point_id(obd_id: int) -> str:
    """OBD 标准码的稳定向量点号。"""
    return f"pg:o:{obd_id}"


def chunk_point_id(chunk_id: int) -> str:
    """手册章节切片的稳定向量点号。"""
    return f"pg:c:{chunk_id}"


def faq_point_id(faq_id: int) -> str:
    """已审客服知识的稳定向量点号。"""
    return f"pg:f:{faq_id}"


def _session(db: Optional[Session]) -> tuple[Session, bool]:
    """没有传入会话时自行打开，并告诉调用方是否需要关闭。"""
    if db is not None:
        return db, False
    return SessionLocal(), True


def _set_ef_search(db: Session) -> None:
    """在当前事务内设置 HNSW ef_search，只影响本连接。"""
    db.execute(
        text("SELECT set_config('hnsw.ef_search', :ef, true)"),
        {"ef": str(settings.PGVECTOR_EF_SEARCH)},
    )


def _vector_literal(vector: Sequence[float]) -> str:
    """把向量转成 pgvector 字面量。"""
    return "[" + ",".join(str(float(x)) for x in vector) + "]"


def _encode_or_none(query: str) -> Optional[List[float]]:
    """编码查询文本；推理服务不可用时返回 None。"""
    try:
        from app.rag.rag_service import encode_text
        return encode_text(query)
    except Exception as exc:
        logger.warning(f"[MultiSource] 查询编码失败，跳过语义路: {exc}")
        return None


def _keyword_rows(db: Session, table: str, tsv_sql: str, query: str, limit: int) -> list:
    """通用 tsvector 关键词检索。"""
    raw = (query or "").strip()
    if not raw:
        return []
    tsq = build_or_tsquery(raw) or build_or_tsquery(" ".join(tokenize_repair_text(raw)))
    if not tsq:
        return []
    sql = text(
        tsv_sql
        + """
        WHERE search_tsv @@ to_tsquery('simple', :tsq)
        ORDER BY score DESC, id DESC
        LIMIT :limit
        """
    )
    return list(db.execute(sql, {"tsq": tsq, "limit": limit, "weights": settings.TS_RANK_WEIGHTS}).fetchall())


def _vector_rows(
    db: Session,
    table: str,
    select_sql: str,
    query_vector: List[float],
    limit: int,
    threshold: float,
    extra_params: Optional[dict] = None,
) -> list:
    """通用 pgvector 检索，分数为 1 - 余弦距离。"""
    max_distance = max(0.0, 1.0 - float(threshold or 0.0))
    _set_ef_search(db)
    params = {
        "q": _vector_literal(query_vector),
        "max_distance": max_distance,
        "limit": limit,
    }
    if extra_params:
        params.update(extra_params)
    return list(db.execute(text(select_sql), params).fetchall())


# ---------- OBD ----------

def _obd_item(row, *, score: float, method: str) -> dict:
    """把 OBD 行转成混合检索统一字典。"""
    content_parts = [row.description_zh or ""]
    if getattr(row, "typical_causes", None):
        content_parts.append(f"常见原因：{row.typical_causes}")
    if getattr(row, "typical_steps", None):
        content_parts.append(f"常规步骤：{row.typical_steps}")
    return {
        "_dedup_key": f"O:{row.id}",
        "id": f"obd-{row.id}",
        "obd_id": row.id,
        "knowledge_id": None,
        "source_type": "OBD",
        "error_code": row.code,
        "fault_code": row.code,
        "title": f"{row.code} {row.title}".strip(),
        "content": "\n".join(p for p in content_parts if p),
        "description_zh": row.description_zh or "",
        "description_en": getattr(row, "description_en", None) or "",
        "typical_causes": getattr(row, "typical_causes", None) or "",
        "typical_steps": getattr(row, "typical_steps", None) or "",
        "standard": getattr(row, "standard", None) or "",
        "device_type": "",
        "score": round(float(score), 4),
        "method": method,
    }


def search_obd_exact(codes: Sequence[str], *, db: Optional[Session] = None, top_k: int = 10) -> List[dict]:
    """按标准码精确命中 OBD 库，命中分记为 1.0。"""
    from app.core.manual_text import normalize_error_code
    wanted = []
    seen = set()
    for code in codes or []:
        token = normalize_error_code(code) or (code or "").upper()
        if token and token not in seen:
            seen.add(token)
            wanted.append(token)
    if not wanted:
        return []
    session, owned = _session(db)
    try:
        from app.models.obd_code import ObdCode
        rows = (
            session.query(ObdCode)
            .filter(ObdCode.code.in_(wanted), ObdCode.status == "PUBLISHED")
            .limit(top_k)
            .all()
        )
        return [_obd_item(row, score=1.0, method="obd_code_exact") for row in rows]
    except Exception as exc:
        logger.warning(f"[MultiSource] OBD 精确检索失败: {exc}")
        return []
    finally:
        if owned:
            session.close()


def search_obd_semantic(query: str, *, top_k: int = 10, db: Optional[Session] = None) -> List[dict]:
    """OBD 语义检索，失败或无法编码时再走关键词。"""
    items = _search_obd_vector(query, top_k=top_k, db=db)
    if items:
        return items
    return search_obd_keyword(query, top_k=top_k, db=db)


def _search_obd_vector(query: str, *, top_k: int, db: Optional[Session]) -> List[dict]:
    """OBD 向量路。"""
    vector = _encode_or_none(query)
    if not vector:
        return []
    session, owned = _session(db)
    try:
        sql = """
            SELECT id, (embedding <=> CAST(:q AS vector)) AS distance
            FROM obd_codes
            WHERE embedding IS NOT NULL
              AND status = 'PUBLISHED'
              AND embedding <=> CAST(:q AS vector) <= :max_distance
            ORDER BY embedding <=> CAST(:q AS vector)
            LIMIT :limit
        """
        hits = _vector_rows(session, "obd_codes", sql, vector, top_k, settings.RETRIEVAL_VECTOR_THRESHOLD)
        if not hits:
            return []
        from app.models.obd_code import ObdCode
        by_id = {row.id: row for row in session.query(ObdCode).filter(ObdCode.id.in_([h.id for h in hits])).all()}
        results = []
        for hit in hits:
            row = by_id.get(hit.id)
            if row is None:
                continue
            results.append(_obd_item(row, score=cosine_distance_to_similarity(hit.distance), method="obd_vector_search"))
        return results
    except Exception as exc:
        logger.warning(f"[MultiSource] OBD 语义检索失败: {exc}")
        return []
    finally:
        if owned:
            session.close()


def search_obd_keyword(query: str, *, top_k: int = 10, db: Optional[Session] = None) -> List[dict]:
    """OBD 关键词检索（已发布条目）。"""
    session, owned = _session(db)
    try:
        tsv_sql = """
            SELECT id, code, title, description_zh, description_en, typical_causes, typical_steps, standard,
                   ts_rank(CAST(:weights AS real[]), search_tsv, to_tsquery('simple', :tsq), 32) AS score
            FROM obd_codes
        """
        # _keyword_rows 会再拼 WHERE search_tsv，这里先把 status 放进 tsv_sql 不方便。
        raw = (query or "").strip()
        if not raw:
            return []
        tsq = build_or_tsquery(raw) or build_or_tsquery(" ".join(tokenize_repair_text(raw)))
        if not tsq:
            return []
        sql = text("""
            SELECT id, code, title, description_zh, description_en, typical_causes, typical_steps, standard,
                   ts_rank(CAST(:weights AS real[]), search_tsv, to_tsquery('simple', :tsq), 32) AS score
            FROM obd_codes
            WHERE search_tsv @@ to_tsquery('simple', :tsq)
              AND status = 'PUBLISHED'
            ORDER BY score DESC, id DESC
            LIMIT :limit
        """)
        rows = session.execute(sql, {"tsq": tsq, "limit": top_k, "weights": settings.TS_RANK_WEIGHTS}).fetchall()
        return [_obd_item(row, score=float(row.score), method="obd_keyword_search") for row in rows]
    except Exception as exc:
        logger.warning(f"[MultiSource] OBD 关键词检索失败: {exc}")
        return []
    finally:
        if owned:
            session.close()


# ---------- 手册章节 ----------

def _chunk_item(row, *, score: float, method: str, manual=None) -> dict:
    """把手册章节行转成统一检索字典。"""
    manual_name = ""
    manual_type = ""
    if manual is not None:
        manual_name = manual.name
        manual_type = manual.manual_type
    elif hasattr(row, "manual_name"):
        manual_name = row.manual_name or ""
        manual_type = getattr(row, "manual_type", "") or ""
    page = row.page_from or ""
    if getattr(row, "page_to", None) and row.page_to != row.page_from:
        page = f"{row.page_from}-{row.page_to}"
    source_type = "TECH_MANUAL" if manual_type == "TECH" else "OEM_MANUAL"
    return {
        "_dedup_key": f"C:{row.id}",
        "id": f"chunk-{row.id}",
        "chunk_id": row.id,
        "manual_id": row.manual_id,
        "source_type": source_type,
        "title": row.title,
        "content": (row.content or "")[:800],
        "chapter": row.chapter or "",
        "section": getattr(row, "section", None) or "",
        "page": page,
        "page_from": row.page_from or "",
        "page_to": getattr(row, "page_to", None) or "",
        "chunk_type": getattr(row, "chunk_type", None) or "",
        "manual_name": manual_name,
        "device_type": "",
        "score": round(float(score), 4),
        "method": method,
    }


def search_manual_chunks_keyword(query: str, *, top_k: int = 10, db: Optional[Session] = None) -> List[dict]:
    """手册章节关键词检索。"""
    session, owned = _session(db)
    try:
        raw = (query or "").strip()
        if not raw:
            return []
        tsq = build_or_tsquery(raw) or build_or_tsquery(" ".join(tokenize_repair_text(raw)))
        if not tsq:
            return []
        sql = text("""
            SELECT c.id, c.manual_id, c.chapter, c.section, c.page_from, c.page_to, c.chunk_type,
                   c.title, c.content, m.name AS manual_name, m.manual_type AS manual_type,
                   ts_rank(CAST(:weights AS real[]), c.search_tsv, to_tsquery('simple', :tsq), 32) AS score
            FROM repair_manual_chunks c
            JOIN repair_manuals m ON m.id = c.manual_id
            WHERE c.search_tsv @@ to_tsquery('simple', :tsq)
              AND c.status = 'PUBLISHED'
              AND m.status = 'PUBLISHED'
            ORDER BY score DESC, c.id DESC
            LIMIT :limit
        """)
        rows = session.execute(sql, {"tsq": tsq, "limit": top_k, "weights": settings.TS_RANK_WEIGHTS}).fetchall()
        return [_chunk_item(row, score=float(row.score), method="manual_chunk_keyword") for row in rows]
    except Exception as exc:
        logger.warning(f"[MultiSource] 手册章节关键词检索失败: {exc}")
        return []
    finally:
        if owned:
            session.close()


def search_manual_chunks_vector(query: str, *, top_k: int = 10, db: Optional[Session] = None) -> List[dict]:
    """手册章节向量检索；编码失败时退回关键词。"""
    vector = _encode_or_none(query)
    if not vector:
        return search_manual_chunks_keyword(query, top_k=top_k, db=db)
    session, owned = _session(db)
    try:
        sql = """
            SELECT c.id, (c.embedding <=> CAST(:q AS vector)) AS distance
            FROM repair_manual_chunks c
            JOIN repair_manuals m ON m.id = c.manual_id
            WHERE c.embedding IS NOT NULL
              AND c.status = 'PUBLISHED'
              AND m.status = 'PUBLISHED'
              AND c.embedding <=> CAST(:q AS vector) <= :max_distance
            ORDER BY c.embedding <=> CAST(:q AS vector)
            LIMIT :limit
        """
        hits = _vector_rows(session, "repair_manual_chunks", sql, vector, top_k, settings.RETRIEVAL_VECTOR_THRESHOLD)
        if not hits:
            return []
        from app.models.repair_manual import RepairManual, RepairManualChunk
        chunks = session.query(RepairManualChunk).filter(RepairManualChunk.id.in_([h.id for h in hits])).all()
        manuals = {m.id: m for m in session.query(RepairManual).filter(RepairManual.id.in_({c.manual_id for c in chunks})).all()}
        by_id = {c.id: c for c in chunks}
        results = []
        for hit in hits:
            row = by_id.get(hit.id)
            if row is None:
                continue
            results.append(_chunk_item(
                row,
                score=cosine_distance_to_similarity(hit.distance),
                method="manual_chunk_vector",
                manual=manuals.get(row.manual_id),
            ))
        return results
    except Exception as exc:
        logger.warning(f"[MultiSource] 手册章节语义检索失败: {exc}")
        return []
    finally:
        if owned:
            session.close()


# ---------- 已审客服知识 ----------

def _faq_item(row, *, score: float, method: str) -> dict:
    """把已审客服知识转成统一检索字典。"""
    return {
        "_dedup_key": f"F:{row.id}",
        "id": f"faq-{row.id}",
        "faq_id": row.id,
        "source_type": "FAQ",
        "title": row.title,
        "content": (row.content or "")[:800],
        "device_type": "",
        "score": round(float(score), 4),
        "method": method,
    }


def search_faq_keyword(query: str, *, top_k: int = 10, db: Optional[Session] = None, store_id: Optional[int] = None) -> List[dict]:
    """已审客服知识的关键词检索。传入 store_id 时只返回该门店或全局（store_id 为空）条目。"""
    session, owned = _session(db)
    try:
        raw = (query or "").strip()
        if not raw:
            return []
        tsq = build_or_tsquery(raw) or build_or_tsquery(" ".join(tokenize_repair_text(raw)))
        if not tsq:
            return []
        sql = text("""
            SELECT id, title, content,
                   ts_rank(CAST(:weights AS real[]), search_tsv, to_tsquery('simple', :tsq), 32) AS score
            FROM consult_faqs
            WHERE search_tsv @@ to_tsquery('simple', :tsq)
              AND status = 'PUBLISHED'
              AND (:store_id IS NULL OR store_id IS NULL OR store_id = :store_id)
            ORDER BY score DESC, id DESC
            LIMIT :limit
        """)
        rows = session.execute(sql, {"tsq": tsq, "limit": top_k, "weights": settings.TS_RANK_WEIGHTS, "store_id": store_id}).fetchall()
        return [_faq_item(row, score=float(row.score), method="faq_keyword_search") for row in rows]
    except Exception as exc:
        logger.warning(f"[MultiSource] 客服知识关键词检索失败: {exc}")
        return []
    finally:
        if owned:
            session.close()


def search_faq_vector(query: str, *, top_k: int = 10, db: Optional[Session] = None, store_id: Optional[int] = None) -> List[dict]:
    """已审客服知识的向量检索；编码失败时退回关键词。传入 store_id 时只返回该门店或全局条目。"""
    vector = _encode_or_none(query)
    if not vector:
        return search_faq_keyword(query, top_k=top_k, db=db, store_id=store_id)
    session, owned = _session(db)
    try:
        store_clause = ""
        extra_params = {}
        if store_id is not None:
            store_clause = " AND (store_id IS NULL OR store_id = :store_id)"
            extra_params["store_id"] = store_id
        sql = """
            SELECT id, (embedding <=> CAST(:q AS vector)) AS distance
            FROM consult_faqs
            WHERE embedding IS NOT NULL
              AND status = 'PUBLISHED'
              AND embedding <=> CAST(:q AS vector) <= :max_distance
        """ + store_clause + """
            ORDER BY embedding <=> CAST(:q AS vector)
            LIMIT :limit
        """
        hits = _vector_rows(session, "consult_faqs", sql, vector, top_k, settings.RETRIEVAL_VECTOR_THRESHOLD, extra_params=extra_params)
        if not hits:
            return []
        from app.models.consult_faq import ConsultFaq
        by_id = {row.id: row for row in session.query(ConsultFaq).filter(ConsultFaq.id.in_([h.id for h in hits])).all()}
        results = []
        for hit in hits:
            row = by_id.get(hit.id)
            if not row:
                continue
            results.append(_faq_item(row, score=cosine_distance_to_similarity(hit.distance), method="faq_vector_search"))
        return results
    except Exception as exc:
        logger.warning(f"[MultiSource] 客服知识语义检索失败: {exc}")
        return []
    finally:
        if owned:
            session.close()


def fetch_linked_sources(source_refs: Sequence[Dict[str, str]], *, db: Optional[Session] = None) -> List[dict]:
    """按图谱关系上的来源编号取出对应条目，作为额外召回集合。

    识别的编号形态：chunk:{id}、obd:{code}、faq:{id}、knowledge:{id}。
    """
    if not source_refs:
        return []
    session, owned = _session(db)
    items: List[dict] = []
    try:
        from app.models.repair_manual import RepairManual, RepairManualChunk
        from app.models.obd_code import ObdCode
        from app.models.consult_faq import ConsultFaq
        from app.models.knowledge import KnowledgeItem

        for ref in source_refs:
            token = (ref.get("ref") or "").strip()
            if ":" not in token:
                continue
            kind, value = token.split(":", 1)
            try:
                if kind == "chunk":
                    row = session.query(RepairManualChunk).filter(RepairManualChunk.id == int(value)).first()
                    if row and row.status == "PUBLISHED":
                        manual = session.query(RepairManual).filter(RepairManual.id == row.manual_id).first()
                        item = _chunk_item(row, score=0.95, method="graph_linked", manual=manual)
                        items.append(item)
                elif kind == "obd":
                    row = session.query(ObdCode).filter(ObdCode.code == value.upper()).first()
                    if row and row.status == "PUBLISHED":
                        items.append(_obd_item(row, score=0.95, method="graph_linked"))
                elif kind == "faq":
                    row = session.query(ConsultFaq).filter(ConsultFaq.id == int(value)).first()
                    if row and row.status == "PUBLISHED":
                        items.append(_faq_item(row, score=0.9, method="graph_linked"))
                elif kind == "knowledge":
                    row = session.query(KnowledgeItem).filter(KnowledgeItem.id == int(value)).first()
                    if row:
                        items.append({
                            "_dedup_key": f"K:{row.id}",
                            "id": row.id,
                            "knowledge_id": row.id,
                            "source_type": "CASE",
                            "title": row.title,
                            "content": (row.content or "")[:800],
                            "device_type": row.device_type or "",
                            "fault_code": row.fault_code or "",
                            "score": 0.9,
                            "method": "graph_linked",
                        })
            except Exception as exc:
                logger.warning(f"[MultiSource] 解析图谱来源 {token} 失败: {exc}")
        return items
    except Exception as exc:
        logger.warning(f"[MultiSource] 读取图谱关联条目失败: {exc}")
        return items
    finally:
        if owned:
            session.close()
