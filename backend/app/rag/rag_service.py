"""统一 RAG 门面：编码 / PostgreSQL 向量读写 / 混合检索 / 精排的唯一对外入口。

分层约定（按现网技术栈改写）：
- 本模块属于 RAG 检索层。API、Agent、脚本不得再直接调用
  app.core.embeddings / vector_store / reranker 或向量存储实现。
- 本模块只封装现有能力，不改检索算法、阈值或降级路径。
- 存储与推理客户端仍在 app.core（embeddings / reranker / vector_store），
  仅允许本包（app.rag）调用。

公开 API 一览
------------
推理探测与编码（签名与 embeddings 对齐）：
    is_server_available, encode_text, encode_texts, get_vector_dimension

知识库向量（knowledge_items.embedding）：
    search_knowledge_vectors, search_knowledge_vectors_by_embedding
    sync_knowledge_item, resync_knowledge_item
    flush_knowledge_vectors, count_knowledge_vectors

手册错误码向量（manual_code_entries.embedding）：
    search_manual_vectors, insert_manual_vector, delete_manual_vector
    drop_and_recreate_manual_collection, flush_manual_vectors

混合检索与精排（实现见 app.rag.retrieval_flow，签名不变）：
    make_tools, retrieve_hybrid, extract_device_and_fault
    filter_rerank_cases, case_rank_score, rank_manual_conditions
    evaluate_retrieval_quality
    repair_intent_fast_check, repair_intent_check, REPAIR_IRRELEVANT_REPLY
"""
from __future__ import annotations

from typing import Any, List, Optional

from app.core.embeddings import (
    encode_text as _encode_text,
    encode_texts as _encode_texts,
    get_vector_dimension as _get_vector_dimension,
    is_server_available as _is_server_available,
)
from app.core.manual_text import build_manual_embedding_text
from app.rag.retrieval_flow import (  # noqa: F401
    REPAIR_IRRELEVANT_REPLY,
    case_rank_score,
    evaluate_retrieval_quality,
    extract_device_and_fault,
    filter_rerank_cases,
    make_tools,
    rank_manual_conditions,
    repair_intent_check,
    repair_intent_fast_check,
    retrieve_hybrid,
)


def is_server_available() -> bool:
    """快速探测推理服务是否可用（短超时，用于降级判断与启动健康检查）。"""
    return _is_server_available()


def encode_text(text: str, max_length: int = 512) -> List[float]:
    """将文本编码为 bge-m3 dense 向量（已 L2 归一化）。"""
    return _encode_text(text, max_length=max_length)


def encode_texts(texts: List[str], max_length: int = 512) -> List[List[float]]:
    """批量编码（一次 HTTP 请求）。"""
    return _encode_texts(texts, max_length=max_length)


def get_vector_dimension() -> int:
    """获取向量维度（从推理服务健康检查读取，失败回退配置值）。"""
    return _get_vector_dimension()


def _knowledge_store():
    """返回知识条目使用的向量存储客户端。延迟导入以免循环依赖，外部应通过 rag_service 的检索函数使用，不要直接操作存储。"""
    from app.core import vector_store as vs
    return vs.vector_store


def _log_code_store():
    """返回手册错误码使用的向量存储客户端，同样延迟导入。"""
    from app.core import vector_store as vs
    return vs.log_code_store


def search_knowledge_vectors(
    query: str,
    *,
    limit: int = 5,
    device_type: Optional[str] = None,
    fault_code: Optional[str] = None,
    score_threshold: float = 0.3,
) -> List[dict]:
    """对查询文本编码后检索知识库向量（knowledge 集合）。"""
    query_vector = encode_text(query)
    return search_knowledge_vectors_by_embedding(
        query_vector,
        limit=limit,
        device_type=device_type,
        fault_code=fault_code,
        score_threshold=score_threshold,
    )


def search_knowledge_vectors_by_embedding(
    query_vector: List[float],
    *,
    limit: int = 5,
    device_type: Optional[str] = None,
    fault_code: Optional[str] = None,
    score_threshold: float = 0.3,
) -> List[dict]:
    """已有查询向量时检索知识库（供批量编码后再逐条检索的脚本使用）。"""
    return _knowledge_store().search(
        query_vector=query_vector,
        limit=limit,
        device_type=device_type,
        fault_code=fault_code,
        score_threshold=score_threshold,
    )


def sync_knowledge_item(item: Any) -> None:
    """将知识条目向量化并写入 PostgreSQL embedding 列，回写稳定点号到 milvus_id（pg:k:{id}）。

    文本拼装保持不变：``f"{title} {content[:MAX_VECTOR_CONTENT_LEN]}"``。
    """
    from app.core.config import settings

    text = f"{item.title} {item.content[:settings.MAX_VECTOR_CONTENT_LEN]}"
    vec = encode_text(text)
    store = _knowledge_store()
    point_id = store.insert(
        vector=vec,
        knowledge_id=item.id,
        title=item.title,
        content=item.content,
        device_type=item.device_type,
        fault_code=item.fault_code,
        fault_tags=item.fault_tags,
    )
    item.milvus_id = point_id


def resync_knowledge_item(item: Any) -> None:
    """按已发布知识条目重灌向量：先清空同 knowledge_id 的 embedding 再写入（可安全重跑）。

    文本拼装与原 scripts/sync_vectors.py 保持一致：
    ``f"{title or ''}\\n{(content or '')[:MAX_VECTOR_CONTENT_LEN]}"``。
    """
    from app.core.config import settings

    text = f"{item.title or ''}\n{(item.content or '')[:settings.MAX_VECTOR_CONTENT_LEN]}"
    vec = encode_text(text)
    store = _knowledge_store()
    store.delete_by_knowledge_id(item.id)
    item.milvus_id = store.insert(
        vector=vec,
        knowledge_id=item.id,
        title=item.title or "",
        content=item.content or "",
        device_type=item.device_type or "",
        fault_code=item.fault_code or "",
        fault_tags=item.fault_tags or [],
    )


def flush_knowledge_vectors() -> None:
    """兼容接口：PostgreSQL 提交即落盘，此处为空操作。"""
    _knowledge_store().flush()


def count_knowledge_vectors() -> int:
    """已写入 embedding 的知识条数。"""
    return _knowledge_store().count()


def search_manual_vectors(
    query_vector: List[float],
    *,
    limit: int = 5,
    device_type: Optional[str] = None,
    error_code: Optional[str] = None,
    score_threshold: float = 0.0,
) -> List[dict]:
    """用已有向量检索手册错误码表的 embedding 列。"""
    return _log_code_store().search(
        query_vector=query_vector,
        limit=limit,
        device_type=device_type,
        error_code=error_code,
        score_threshold=score_threshold,
    )


def insert_manual_vector(manual_code_id: int, data: dict) -> str:
    """按手册条目字段编码并写入 embedding 列，返回稳定点号 pg:m:{id}。"""
    vector = encode_text(build_manual_embedding_text(data))
    point_id = _log_code_store().insert(
        vector=vector,
        manual_code_id=manual_code_id,
        error_code=data["error_code"],
        manual_name=data["manual_name"],
        device_type=data.get("device_type"),
        title=data["title"],
        description=data["description"],
        chapter=data.get("chapter") or "",
        page=data.get("page") or "",
    )
    return str(point_id)


def delete_manual_vector(point_id: str) -> bool:
    """清空手册条目的 embedding，不删除手册行。"""
    return _log_code_store().delete(point_id)


def drop_and_recreate_manual_collection() -> None:
    """清空全部手册 embedding，供导入脚本 --force-rebuild 后重灌。不删除手册行。"""
    _log_code_store().drop_collection()


def flush_manual_vectors() -> None:
    """兼容接口：PostgreSQL 提交即落盘，此处为空操作。"""
    _log_code_store().flush()


def upsert_row_embedding(table: str, row_id: int, text_value: str, point_id: str) -> str:
    """把一段文本编码后写入指定表的 embedding 和 point_id。推理服务不可用时抛错给调用方处理。"""
    from sqlalchemy import text as _sql
    from app.core.database import SessionLocal
    from app.core.vector_store import _vector_literal

    allowed = {
        "obd_codes": "obd",
        "repair_manual_chunks": "chunk",
        "consult_faqs": "faq",
    }
    if table not in allowed:
        raise ValueError(f"不支持为表 {table} 写 embedding")
    vector = encode_text(text_value)
    db = SessionLocal()
    try:
        db.execute(
            _sql(
                f"UPDATE {table} "
                "SET embedding = CAST(:embedding AS vector), point_id = :point_id "
                "WHERE id = :id"
            ),
            {"embedding": _vector_literal(vector), "point_id": point_id, "id": row_id},
        )
        db.commit()
        return point_id
    finally:
        db.close()

