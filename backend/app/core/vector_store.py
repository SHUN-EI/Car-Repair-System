"""PostgreSQL pgvector 向量库封装：知识表与手册错误码表共用检索逻辑。

语义向量写在业务表的 embedding 列上，不再使用 Milvus。
API 层不应直接调用本模块，应走 rag_service。
对外方法名与参数与原 Milvus 封装对齐，便于检索漏斗零改动：
insert / update / search / delete / delete_by_knowledge_id / flush / count / drop_collection。
返回的 score 已从余弦距离还原为相似度（1 - 距离），阈值刻度保持不变。
"""
from __future__ import annotations

from typing import Any, List, Dict, Optional

from loguru import logger
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.rag.lexical import (
    cosine_distance_to_similarity,
    knowledge_point_id,
    manual_point_id,
    parse_point_id,
)


def _session():
    """打开一个短会话，调用方必须关闭。"""
    return SessionLocal()


class VectorStore:
    """知识库向量存储（knowledge_items.embedding）。

    一条已同步的知识对应一行 embedding；未同步或已删除向量时该列为空，不进入召回。
    collection_name 参数仅为兼容旧调用签名，不再对应外部集合。
    """

    def __init__(self, collection_name: Optional[str] = None, fields: Optional[List] = None,
                 description: str = ""):
        """记录可选的兼容参数。真正读写发生在首次 search/insert，不需要单独建集合。"""
        self.collection_name = collection_name or "knowledge"
        self.vector_size = settings.VECTOR_DIM
        self._description = description or "pgvector: knowledge_items.embedding"

    def _set_ef_search(self, db) -> None:
        """在当前事务内设置 HNSW ef_search，只影响本连接。"""
        ef = int(getattr(settings, "PGVECTOR_EF_SEARCH", 64) or 64)
        db.execute(text("SELECT set_config('hnsw.ef_search', :ef, true)"), {"ef": str(ef)})

    def _validate_vector(self, vector: List[float]) -> List[float]:
        """校验向量维度，避免写入与索引不一致的长度。"""
        if not vector or len(vector) != self.vector_size:
            raise ValueError(
                f"向量维度必须是 {self.vector_size}（bge-m3），实际为 {0 if not vector else len(vector)}"
            )
        return [float(x) for x in vector]

    def insert(
        self,
        vector: List[float],
        knowledge_id: int,
        title: str,
        content: str,
        device_type: Optional[str] = None,
        fault_code: Optional[str] = None,
        fault_tags: Optional[List] = None,
        point_id: Optional[str] = None,
    ) -> str:
        """把向量写入对应知识行。已有 embedding 时覆盖，返回稳定点号 pg:k:{id}。

        title/content/device_type 等字段以 PostgreSQL 正本为准，这里不再另存一份副本；
        参数保留是为了与原 Milvus insert 签名兼容。
        """
        return self._upsert_knowledge(knowledge_id, vector, point_id=point_id)

    def update(
        self,
        point_id: str,
        vector: List[float],
        title: str,
        content: str,
        device_type: Optional[str] = None,
        fault_code: Optional[str] = None,
        fault_tags: Optional[List] = None,
    ) -> None:
        """按点号或 milvus_id 兼容字段更新已有知识向量。"""
        kid = self._resolve_knowledge_id(point_id)
        if kid is None:
            raise ValueError(f"找不到要更新的知识向量: {point_id}")
        self._upsert_knowledge(kid, vector, point_id=point_id)

    def _upsert_knowledge(self, knowledge_id: int, vector: List[float], point_id: Optional[str] = None) -> str:
        """写入或覆盖 knowledge_items.embedding，并回写稳定点号到 milvus_id。"""
        vec = self._validate_vector(vector)
        new_id = knowledge_point_id(knowledge_id)
        db = _session()
        try:
            row = db.execute(
                text(
                    "UPDATE knowledge_items "
                    "SET embedding = CAST(:embedding AS vector), milvus_id = :point_id "
                    "WHERE id = :id "
                    "RETURNING id"
                ),
                {"embedding": _vector_literal(vec), "point_id": new_id, "id": knowledge_id},
            ).fetchone()
            if row is None:
                raise ValueError(f"知识条目不存在，无法写入向量: {knowledge_id}")
            db.commit()
            logger.debug(f"知识向量已写入 pgvector: {new_id}")
            return new_id
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _resolve_knowledge_id(self, point_id: str) -> Optional[int]:
        """从 pg:k:{id} 或历史 milvus_id 反查知识主键。"""
        parsed = parse_point_id(point_id)
        if parsed and parsed[0] == "knowledge":
            return parsed[1]
        db = _session()
        try:
            row = db.execute(
                text("SELECT id FROM knowledge_items WHERE milvus_id = :pid"),
                {"pid": point_id},
            ).fetchone()
            return int(row.id) if row else None
        finally:
            db.close()

    def flush(self) -> None:
        """PostgreSQL 在事务提交时已落盘，保留空实现以兼容旧刷写调用。"""
        return None

    def search(
        self,
        query_vector: List[float],
        limit: int = 5,
        device_type: Optional[str] = None,
        fault_code: Optional[str] = None,
        score_threshold: float = 0.3,
        published_only: bool = True,
    ) -> List[Dict]:
        """按余弦距离检索知识向量，返回相似度分（1 - 距离）及条目字段。

        只召回 embedding 非空的行；设备类型精确过滤，故障码仍为包含匹配。
        问诊检索默认只取已发布条目；知识去重需要把 published_only 设为 False，才能看到草稿和审核中的相似条目。
        """
        vec = self._validate_vector(query_vector)
        max_distance = 1.0 - float(score_threshold or 0.0)
        clauses = ["embedding IS NOT NULL", "embedding <=> CAST(:q AS vector) <= :max_distance"]
        params: Dict[str, Any] = {
            "q": _vector_literal(vec),
            "max_distance": max_distance,
            "limit": int(limit),
        }
        if published_only:
            clauses.append("status = 'PUBLISHED'")
        if device_type:
            clauses.append("device_type = :device_type")
            params["device_type"] = device_type
        if fault_code:
            clauses.append("fault_code ILIKE :fault_code")
            params["fault_code"] = f"%{fault_code}%"

        sql = text(
            "SELECT id, milvus_id, title, content, device_type, fault_code, fault_tags, "
            "       (embedding <=> CAST(:q AS vector)) AS distance "
            "FROM knowledge_items "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY embedding <=> CAST(:q AS vector) "
            "LIMIT :limit"
        )
        db = _session()
        try:
            self._set_ef_search(db)
            rows = db.execute(sql, params).fetchall()
            output = []
            for row in rows:
                score = cosine_distance_to_similarity(row.distance)
                kid = int(row.id)
                output.append({
                    "id": row.milvus_id or knowledge_point_id(kid),
                    "score": round(score, 6),
                    "knowledge_id": kid,
                    "title": row.title or "",
                    "content": (row.content or "")[:65000],
                    "device_type": row.device_type or "",
                    "fault_code": row.fault_code or "",
                    "fault_tags": row.fault_tags or [],
                })
            return output
        finally:
            db.close()

    def delete(self, point_id: str) -> bool:
        """按点号清空知识向量，不删除知识行。找不到行时返回 False。"""
        kid = self._resolve_knowledge_id(point_id)
        if kid is None:
            return False
        return self.delete_by_knowledge_id(kid)

    def delete_by_knowledge_id(self, knowledge_id: int) -> bool:
        """按知识主键清空 embedding 与 milvus_id。"""
        db = _session()
        try:
            row = db.execute(
                text(
                    "UPDATE knowledge_items "
                    "SET embedding = NULL, milvus_id = NULL "
                    "WHERE id = :id "
                    "RETURNING id"
                ),
                {"id": knowledge_id},
            ).fetchone()
            db.commit()
            return row is not None
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_by_id(self, point_id: str) -> Optional[Dict]:
        """按点号读取一条知识向量的元数据，不计算相似度。"""
        kid = self._resolve_knowledge_id(point_id)
        if kid is None:
            return None
        db = _session()
        try:
            row = db.execute(
                text(
                    "SELECT id, milvus_id, title, content, device_type, fault_code, fault_tags "
                    "FROM knowledge_items WHERE id = :id"
                ),
                {"id": kid},
            ).fetchone()
            if not row:
                return None
            return {
                "id": row.milvus_id or knowledge_point_id(int(row.id)),
                "knowledge_id": int(row.id),
                "title": row.title or "",
                "content": row.content or "",
                "device_type": row.device_type or "",
                "fault_code": row.fault_code or "",
                "fault_tags": row.fault_tags or [],
            }
        finally:
            db.close()

    def count(self) -> int:
        """已写入向量的知识条数。"""
        db = _session()
        try:
            row = db.execute(text("SELECT COUNT(*) AS n FROM knowledge_items WHERE embedding IS NOT NULL")).fetchone()
            return int(row.n) if row else 0
        finally:
            db.close()

    def drop_collection(self) -> None:
        """清空全部知识向量，保留知识行。名称沿用旧接口，便于脚本 --force-rebuild。"""
        db = _session()
        try:
            db.execute(text("UPDATE knowledge_items SET embedding = NULL, milvus_id = NULL"))
            db.commit()
            logger.warning("已清空 knowledge_items.embedding")
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


class LogCodeVectorStore(VectorStore):
    """手册错误码向量存储（manual_code_entries.embedding），与知识向量隔离。"""

    def __init__(self, collection_name: Optional[str] = None):
        """兼容旧的集合名参数，实际写入 manual_code_entries.embedding。"""
        super().__init__(collection_name=collection_name or "log_code")
        self.collection_name = collection_name or "log_code"
        self._description = "pgvector: manual_code_entries.embedding"

    def insert(
        self,
        vector: List[float],
        manual_code_id: int,
        error_code: str,
        manual_name: str,
        device_type: Optional[str],
        title: str,
        description: str,
        chapter: str = "",
        page: str = "",
        point_id: Optional[str] = None,
    ) -> str:
        """把手册条目向量写入本行，返回稳定点号 pg:m:{id}。其它字段以正本为准。"""
        vec = self._validate_vector(vector)
        new_id = manual_point_id(manual_code_id)
        db = _session()
        try:
            row = db.execute(
                text(
                    "UPDATE manual_code_entries "
                    "SET embedding = CAST(:embedding AS vector), milvus_id = :point_id "
                    "WHERE id = :id "
                    "RETURNING id"
                ),
                {"embedding": _vector_literal(vec), "point_id": new_id, "id": manual_code_id},
            ).fetchone()
            if row is None:
                raise ValueError(f"手册条目不存在，无法写入向量: {manual_code_id}")
            db.commit()
            logger.debug(f"手册向量已写入 pgvector: {new_id}")
            return new_id
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _resolve_manual_id(self, point_id: str) -> Optional[int]:
        """从 pg:m:{id} 或历史 milvus_id 反查手册主键。"""
        parsed = parse_point_id(point_id)
        if parsed and parsed[0] == "manual":
            return parsed[1]
        db = _session()
        try:
            row = db.execute(
                text("SELECT id FROM manual_code_entries WHERE milvus_id = :pid"),
                {"pid": point_id},
            ).fetchone()
            return int(row.id) if row else None
        finally:
            db.close()

    def delete(self, point_id: str) -> bool:
        """按点号清空手册向量，不删除手册行。"""
        mid = self._resolve_manual_id(point_id)
        if mid is None:
            return False
        db = _session()
        try:
            row = db.execute(
                text(
                    "UPDATE manual_code_entries "
                    "SET embedding = NULL, milvus_id = NULL "
                    "WHERE id = :id "
                    "RETURNING id"
                ),
                {"id": mid},
            ).fetchone()
            db.commit()
            return row is not None
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def drop_collection(self) -> None:
        """清空全部手册向量，保留手册行。"""
        db = _session()
        try:
            db.execute(text("UPDATE manual_code_entries SET embedding = NULL, milvus_id = NULL"))
            db.commit()
            logger.warning("已清空 manual_code_entries.embedding")
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def count(self) -> int:
        """已写入向量的手册条数。"""
        db = _session()
        try:
            row = db.execute(
                text("SELECT COUNT(*) AS n FROM manual_code_entries WHERE embedding IS NOT NULL")
            ).fetchone()
            return int(row.n) if row else 0
        finally:
            db.close()

    def search(
        self,
        query_vector: List[float],
        limit: int = 5,
        device_type: Optional[str] = None,
        error_code: Optional[str] = None,
        score_threshold: float = 0.0,
    ) -> List[Dict]:
        """按余弦距离检索手册向量，可叠加设备类型和错误码精确过滤。"""
        vec = self._validate_vector(query_vector)
        max_distance = 1.0 - float(score_threshold or 0.0)
        clauses = ["embedding IS NOT NULL", "embedding <=> CAST(:q AS vector) <= :max_distance"]
        params: Dict[str, Any] = {
            "q": _vector_literal(vec),
            "max_distance": max_distance,
            "limit": int(limit),
        }
        if device_type:
            clauses.append("device_type = :device_type")
            params["device_type"] = device_type
        if error_code:
            clauses.append("error_code = :error_code")
            params["error_code"] = error_code

        sql = text(
            "SELECT id, milvus_id, error_code, manual_name, device_type, title, "
            "       description, chapter, page, "
            "       (embedding <=> CAST(:q AS vector)) AS distance "
            "FROM manual_code_entries "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY embedding <=> CAST(:q AS vector) "
            "LIMIT :limit"
        )
        db = _session()
        try:
            self._set_ef_search(db)
            rows = db.execute(sql, params).fetchall()
            output = []
            for row in rows:
                score = cosine_distance_to_similarity(row.distance)
                mid = int(row.id)
                output.append({
                    "id": row.milvus_id or manual_point_id(mid),
                    "score": round(score, 6),
                    "manual_code_id": mid,
                    "error_code": row.error_code or "",
                    "manual_name": row.manual_name or "",
                    "device_type": row.device_type or "",
                    "title": row.title or "",
                    "description": row.description or "",
                    "chapter": row.chapter or "",
                    "page": row.page or "",
                })
            return output
        finally:
            db.close()


def _vector_literal(vector: List[float]) -> str:
    """把 Python 浮点列表格式化成 pgvector 可 CAST 的文本，如 '[0.1,0.2]'。"""
    return "[" + ",".join(f"{x:.8f}" for x in vector) + "]"


# 全局单例（签名保持不变，检索流仍注入这两个对象）
vector_store = VectorStore()
log_code_store = LogCodeVectorStore()
