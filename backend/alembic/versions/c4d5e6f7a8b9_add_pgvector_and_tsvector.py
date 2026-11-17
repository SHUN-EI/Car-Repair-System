"""add pgvector embeddings and tsvector lexical search

Revision ID: c4d5e6f7a8b9
Revises: a9b8c7d6e5f4
Create Date: 2026-11-17 22:30:00.000000

将语义向量从 Milvus 迁到 PostgreSQL pgvector，并把知识库关键词路
从 ILIKE n-gram 升级为 tsvector。中文分词不引入 zhparser：用
repair_text_tokens() 生成 2/3-gram 与英文记号，再交给 simple 词典。
向量列需要手工回灌（发布审核或 scripts/sync_vectors.py），本迁移只建列和索引。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 与 app.rag.lexical.tokenize_repair_text 保持同一套规则（中文 2/3-gram + 英文/数字词）。
_REPAIR_TEXT_TOKENS = r"""
CREATE OR REPLACE FUNCTION repair_text_tokens(src text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $fn$
DECLARE
    result text := '';
    span text;
    i int;
    n int;
    non_cn text;
    w text;
BEGIN
    IF src IS NULL OR btrim(src) = '' THEN
        RETURN '';
    END IF;
    FOR span IN
        SELECT m[1] FROM regexp_matches(src, '[一-鿿]+', 'g') AS m
    LOOP
        result := result || ' ' || span;
        FOR i IN 1..char_length(span) LOOP
            FOR n IN 2..3 LOOP
                IF i + n - 1 <= char_length(span) THEN
                    result := result || ' ' || substr(span, i, n);
                END IF;
            END LOOP;
        END LOOP;
    END LOOP;
    non_cn := regexp_replace(src, '[一-鿿]+', ' ', 'g');
    FOREACH w IN ARRAY regexp_split_to_array(btrim(non_cn), '[[:space:]]+')
    LOOP
        IF char_length(w) >= 2 THEN
            result := result || ' ' || w;
        END IF;
    END LOOP;
    RETURN btrim(result);
END;
$fn$;
"""

_KNOWLEDGE_TSV = r"""
CREATE OR REPLACE FUNCTION knowledge_search_tsv(
    title text,
    content text,
    fault_code text,
    fault_tags jsonb
)
RETURNS tsvector
LANGUAGE sql
IMMUTABLE
AS $fn$
    SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(title, ''))), 'A')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(fault_code, ''))), 'A')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(content, ''))), 'B')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(fault_tags::text, ''))), 'C')
$fn$;
"""


def upgrade() -> None:
    # pgvector 需要镜像内带有扩展文件；开发编排改用 pgvector/pgvector:pg16。
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(_REPAIR_TEXT_TOKENS)
    op.execute(_KNOWLEDGE_TSV)

    op.execute("ALTER TABLE knowledge_items ADD COLUMN IF NOT EXISTS embedding vector(1024)")
    op.execute(
        "ALTER TABLE knowledge_items ADD COLUMN IF NOT EXISTS search_tsv tsvector "
        "GENERATED ALWAYS AS (knowledge_search_tsv(title, content, fault_code, fault_tags)) STORED"
    )
    op.execute("ALTER TABLE manual_code_entries ADD COLUMN IF NOT EXISTS embedding vector(1024)")

    # 门店知识量适合 HNSW；度量与历史 Milvus COSINE 一致（查询时用 1-距离 还原相似度）。
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_items_embedding_hnsw "
        "ON knowledge_items USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_manual_code_entries_embedding_hnsw "
        "ON manual_code_entries USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_items_search_tsv "
        "ON knowledge_items USING gin (search_tsv)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_knowledge_items_search_tsv")
    op.execute("DROP INDEX IF EXISTS idx_manual_code_entries_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_knowledge_items_embedding_hnsw")
    op.execute("ALTER TABLE manual_code_entries DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE knowledge_items DROP COLUMN IF EXISTS search_tsv")
    op.execute("ALTER TABLE knowledge_items DROP COLUMN IF EXISTS embedding")
    op.execute("DROP FUNCTION IF EXISTS knowledge_search_tsv(text, text, text, jsonb)")
    op.execute("DROP FUNCTION IF EXISTS repair_text_tokens(text)")
    # vector 扩展可能被手工它用，降级时保留。
