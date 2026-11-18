-- 迁移追加、模型字段上未直接声明的索引。
-- 来源：7a8b9c0d1e2f（pg_trgm）与 c4d5e6f7a8b9（HNSW / GIN）。

CREATE INDEX IF NOT EXISTS idx_knowledge_items_embedding_hnsw
    ON knowledge_items USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_manual_code_entries_embedding_hnsw
    ON manual_code_entries USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_knowledge_items_search_tsv
    ON knowledge_items USING gin (search_tsv);

CREATE INDEX IF NOT EXISTS idx_knowledge_title_trgm
    ON knowledge_items USING gin (title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_knowledge_content_trgm
    ON knowledge_items USING gin (content gin_trgm_ops);
