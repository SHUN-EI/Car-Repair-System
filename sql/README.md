# 现网表结构建表语句

本目录是对照当前 `backend/app/models/` 与 Alembic 头修订 `d6e7f8a9b0c1` 整理的 PostgreSQL 建表快照，共 43 张表。字段、类型、外键和索引以模型为准，并补上了迁移里才有的扩展、函数、生成列和 HNSW / GIN / `pg_trgm` 索引。

对已经在跑的库，请继续用 Alembic 升级，不要用这些文件替代迁移，也不要用仓库根目录的 `init-db.sql` 建库（该文件已过时）。

在空库上若只想对照结构，按文件名顺序执行：

1. `00_extensions.sql` — `vector`、`pg_trgm`
2. `01_functions.sql` — `repair_text_tokens()`、`knowledge_search_tsv()`、`obd_search_tsv()`、`chunk_search_tsv()`、`faq_search_tsv()`
3. `02_enums.sql` — `workorderstatus`、`knowledgestatus`
4. `03_tables.sql` — 全部 `CREATE TABLE`、列注释与模型中的索引
5. `04_indexes.sql` — 迁移追加的向量 / 全文 / 三gram 索引

说明：

- 应用侧默认值（例如角色默认 `TECHNICIAN`、多数表的 `created_at`）若模型和迁移都没有 `server_default`，建表语句里就不会写数据库 `DEFAULT`。
- 迁移里带了 `server_default` 的列（如预约状态 `PENDING`、支付意向 `CNY`/`STUB`）已写入对应的 `DEFAULT`。
- `fault_code_mappings`、`fault_phenomenon_categories`、`root_cause_categories` 只在模型里定义，Alembic 迁移链没有对应的 `create_table`。只跑迁移的空库不会自动出现这三张表，语句仍一并写出，便于对照模型。

- `d6e7f8a9b0c1` 新增 9 张多源 RAG 表：`rag_sources`、`obd_codes`、`repair_manuals`、`repair_manual_chunks`、`kg_entities`、`kg_relations`、`consult_conversations`、`consult_messages`、`consult_faqs`。对已在跑的库请执行 `alembic upgrade head`，不要用本目录替代迁移。
