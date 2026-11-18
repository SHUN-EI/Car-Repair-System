"""add multi-source RAG tables, OBD library and PostgreSQL graph

Revision ID: d6e7f8a9b0c1
Revises: c4d5e6f7a8b9
Create Date: 2026-11-18 18:40:00.000000

为多源 RAG 增加来源登记、OBD 标准码、原厂/技术手册及章节切片、
咨询会话与已审客服知识、以及 PostgreSQL 实体/关系表。
检索协议仍走 retrieve_hybrid；新列的向量需脚本或发布时回灌。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OBD_TSV = r"""
CREATE OR REPLACE FUNCTION obd_search_tsv(
    code text,
    title text,
    description_zh text,
    typical_causes text,
    typical_steps text
)
RETURNS tsvector
LANGUAGE sql
IMMUTABLE
AS $fn$
    SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(code, ''))), 'A')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(title, ''))), 'A')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(description_zh, ''))), 'B')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(typical_causes, ''))), 'B')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(typical_steps, ''))), 'C')
$fn$;
"""

_CHUNK_TSV = r"""
CREATE OR REPLACE FUNCTION chunk_search_tsv(
    title text,
    content text,
    chapter text
)
RETURNS tsvector
LANGUAGE sql
IMMUTABLE
AS $fn$
    SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(title, ''))), 'A')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(chapter, ''))), 'A')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(content, ''))), 'B')
$fn$;
"""

_FAQ_TSV = r"""
CREATE OR REPLACE FUNCTION faq_search_tsv(
    title text,
    content text
)
RETURNS tsvector
LANGUAGE sql
IMMUTABLE
AS $fn$
    SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(title, ''))), 'A')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(content, ''))), 'B')
$fn$;
"""


def upgrade() -> None:
    """建多源 RAG 表、生成列和检索索引。"""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(_OBD_TSV)
    op.execute(_CHUNK_TSV)
    op.execute(_FAQ_TSV)

    op.execute("""
        CREATE TABLE IF NOT EXISTS rag_sources (
            id SERIAL PRIMARY KEY,
            source_kind VARCHAR(40) NOT NULL,
            title VARCHAR(300) NOT NULL,
            publisher VARCHAR(200),
            version VARCHAR(80),
            applicability JSONB,
            file_uri TEXT,
            checksum VARCHAR(64),
            copyright_note TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
            ingested_at TIMESTAMP,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_rag_sources_source_kind ON rag_sources (source_kind)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_rag_sources_status ON rag_sources (status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS obd_codes (
            id SERIAL PRIMARY KEY,
            code VARCHAR(20) NOT NULL,
            system VARCHAR(1),
            title VARCHAR(300) NOT NULL,
            description_zh TEXT NOT NULL,
            description_en TEXT,
            typical_causes TEXT,
            typical_steps TEXT,
            standard VARCHAR(80) DEFAULT 'SAE J2012',
            source_id INTEGER REFERENCES rag_sources(id),
            status VARCHAR(20) NOT NULL DEFAULT 'PUBLISHED',
            embedding vector(1024),
            search_tsv tsvector GENERATED ALWAYS AS (
                obd_search_tsv(code, title, description_zh, typical_causes, typical_steps)
            ) STORED,
            point_id VARCHAR(100),
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_obd_codes_code ON obd_codes (code)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_obd_codes_point_id ON obd_codes (point_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_obd_codes_status ON obd_codes (status)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_obd_codes_embedding_hnsw
        ON obd_codes USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_obd_codes_search_tsv ON obd_codes USING gin (search_tsv)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS repair_manuals (
            id SERIAL PRIMARY KEY,
            source_id INTEGER REFERENCES rag_sources(id),
            name VARCHAR(300) NOT NULL,
            manual_type VARCHAR(20) NOT NULL DEFAULT 'OEM',
            make VARCHAR(100),
            model VARCHAR(100),
            year_from INTEGER,
            year_to INTEGER,
            language VARCHAR(20) DEFAULT 'zh',
            version VARCHAR(80),
            file_uri TEXT,
            copyright_note TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_repair_manuals_status ON repair_manuals (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_repair_manuals_make_model ON repair_manuals (make, model)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS repair_manual_chunks (
            id SERIAL PRIMARY KEY,
            manual_id INTEGER NOT NULL REFERENCES repair_manuals(id),
            chapter VARCHAR(200),
            section VARCHAR(200),
            page_from VARCHAR(50),
            page_to VARCHAR(50),
            chunk_type VARCHAR(40),
            title VARCHAR(300) NOT NULL,
            content TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
            embedding vector(1024),
            search_tsv tsvector GENERATED ALWAYS AS (
                chunk_search_tsv(title, content, chapter)
            ) STORED,
            point_id VARCHAR(100),
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_repair_manual_chunks_manual_id ON repair_manual_chunks (manual_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_repair_manual_chunks_point_id ON repair_manual_chunks (point_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_repair_manual_chunks_status ON repair_manual_chunks (status)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_repair_manual_chunks_embedding_hnsw
        ON repair_manual_chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_repair_manual_chunks_search_tsv ON repair_manual_chunks USING gin (search_tsv)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS kg_entities (
            id SERIAL PRIMARY KEY,
            entity_type VARCHAR(40) NOT NULL,
            name VARCHAR(200) NOT NULL,
            canonical_key VARCHAR(200) NOT NULL,
            aliases JSONB,
            properties JSONB,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_kg_entities_canonical_key ON kg_entities (canonical_key)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_kg_entities_entity_type ON kg_entities (entity_type)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS kg_relations (
            id SERIAL PRIMARY KEY,
            subject_id INTEGER NOT NULL REFERENCES kg_entities(id),
            predicate VARCHAR(80) NOT NULL,
            object_id INTEGER NOT NULL REFERENCES kg_entities(id),
            properties JSONB,
            source_kind VARCHAR(40) NOT NULL,
            source_ref VARCHAR(80) NOT NULL,
            confidence DOUBLE PRECISION DEFAULT 1.0,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            CONSTRAINT uq_kg_relations_triple_source
                UNIQUE (subject_id, predicate, object_id, source_kind, source_ref)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_kg_relations_subject_pred ON kg_relations (subject_id, predicate)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_kg_relations_object_pred ON kg_relations (object_id, predicate)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS consult_conversations (
            id SERIAL PRIMARY KEY,
            channel VARCHAR(40) NOT NULL,
            store_id INTEGER REFERENCES stores(id),
            staff_user_id INTEGER REFERENCES users(id),
            status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_consult_conversations_store_id ON consult_conversations (store_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS consult_messages (
            id SERIAL PRIMARY KEY,
            conversation_id INTEGER NOT NULL REFERENCES consult_conversations(id),
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_consult_messages_conversation_id ON consult_messages (conversation_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS consult_faqs (
            id SERIAL PRIMARY KEY,
            title VARCHAR(300) NOT NULL,
            content TEXT NOT NULL,
            source_conversation_id INTEGER REFERENCES consult_conversations(id),
            store_id INTEGER REFERENCES stores(id),
            status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
            embedding vector(1024),
            search_tsv tsvector GENERATED ALWAYS AS (
                faq_search_tsv(title, content)
            ) STORED,
            point_id VARCHAR(100),
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_consult_faqs_point_id ON consult_faqs (point_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_consult_faqs_status ON consult_faqs (status)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_consult_faqs_embedding_hnsw
        ON consult_faqs USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_consult_faqs_search_tsv ON consult_faqs USING gin (search_tsv)")


def downgrade() -> None:
    """按依赖反序删除多源表和生成函数。"""
    op.execute("DROP TABLE IF EXISTS consult_faqs")
    op.execute("DROP TABLE IF EXISTS consult_messages")
    op.execute("DROP TABLE IF EXISTS consult_conversations")
    op.execute("DROP TABLE IF EXISTS kg_relations")
    op.execute("DROP TABLE IF EXISTS kg_entities")
    op.execute("DROP TABLE IF EXISTS repair_manual_chunks")
    op.execute("DROP TABLE IF EXISTS repair_manuals")
    op.execute("DROP TABLE IF EXISTS obd_codes")
    op.execute("DROP TABLE IF EXISTS rag_sources")
    op.execute("DROP FUNCTION IF EXISTS faq_search_tsv(text, text)")
    op.execute("DROP FUNCTION IF EXISTS chunk_search_tsv(text, text, text)")
    op.execute("DROP FUNCTION IF EXISTS obd_search_tsv(text, text, text, text, text)")
