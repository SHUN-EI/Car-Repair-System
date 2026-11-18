-- 扩展：对照 Alembic 7a8b9c0d1e2f（pg_trgm）与 c4d5e6f7a8b9（vector）
-- 需要 PostgreSQL 镜像内带有 pgvector（开发编排使用 pgvector/pgvector:pg16）。

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
