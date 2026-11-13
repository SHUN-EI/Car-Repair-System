# 项目架构 Harness 契约（按现网技术栈改写）

本文档是对用户给出的「项目架构 Harness 契约」的落地版本：分层和依赖方向按契约执行，存储与模型以**本仓库现网技术栈**为准，不把契约里与现网不符的组件在本轮引入。

## 1. 分层定义（固定）

1. **API 接入层**（`app/api`、`app/main.py`）：接收 HTTP 请求、参数校验、鉴权；禁止写业务逻辑与检索逻辑。
2. **Agent 编排层**（`app/agents` 中的 LangGraph / 门面 Agent）：Skill 编排、会话状态机。多轮追踪维修与专家模式仍留在 Redis 状态机，不搬到 LangGraph。
3. **RAG 检索层**（`app/rag`）：文本向量、稀疏 BM25、混合检索、Rerank。外部统一走 `app.rag.rag_service`。
4. **业务工具层**：配件查询、工单、外部接口调用。
5. **存储层**：Milvus 向量库、**PostgreSQL** 事实库、Redis 会话缓存。对应客户端在 `app.core`（`vector_store` / `database` / Redis 封装）。

## 2. 依赖方向【强约束】

- 允许：上层 → 下层调用。
- 禁止：下层反向依赖上层；跨层直接调用（API 层不能直接调 Milvus / `vector_store` / `encode_text` / reranker）。
- 向量检索只能封装在 `rag_service` 内部，外部统一走 `rag_service` 接口。

## 3. 接口契约

- 所有对外函数、HTTP 接口、工具入参、返回 JSON 结构，重构必须兼容。
- 新增字段只能可选，不能删除原有字段；错误码体系保持不变。
- 旧 Python 导入路径需保留 shim / 再导出（例如 `from app.agents.retrieval_flow import ...` 仍可用）。

## 4. 模型与组件约束（现网改写）

| 项 | 契约原文 | 本仓库口径 |
| --- | --- | --- |
| 事实库 | MySQL | **PostgreSQL**，不引入 MySQL |
| 图像向量 | CN-CLIP | **本仓库无此链路，不引入 CN-CLIP** |
| 文本 Embedding | BGE-M3 | **BAAI/bge-m3**（现网，保持不变） |
| Reranker | BGE-Reranker | **现网：`BAAI/bge-reranker-v2-m3`**（第二批已替换）。质量阀门阈值（0.45 / 0.6 / 0.7）仍按原 Qwen3-Reranker 的 0~1 分标定，尚未重标；换模型后排序与「结果是否充足」的判断可能变化 |
| 记忆三层 | 工作记忆 / 短期 Redis / 长期 MySQL | 工作记忆 + 短期会话 Redis + **长期事实 PostgreSQL**（不引入 MySQL）。统一门面：`backend/app/memory/memory_service.py`。现网**没有独立长期记忆事实表**，未新造表；会话摘要只做计算并写回短期会话 payload |
| 检索门面 | `rag_service` | `backend/app/rag/rag_service.py` |

`app/core/embeddings.py`、`reranker.py`、`vector_store.py`、`embedding_server.py` 保留为存储 / 推理客户端，只许 RAG 层调用。

## 5. 重构规则

1. 等价重构优先：不新增业务功能，不修改原有逻辑行为。
2. 改动前先输出方案清单、风险点；分批修改，禁止一次性全量重构。
3. 每批次改动后，对照本 Harness 自检；输出回归验证用例。
4. 遇到和 Harness 冲突、边界模糊的地方，停止修改，先提问确认。
5. 新增依赖必须先说明理由，未经允许不能引入新模型 / 新中间件。

## 6. 批次划分

1. **第一批**：新增 `rag_service`，把编码 / Milvus 读写 / 混合检索 / 精排收口；检索算法与阈值不变；当时 Reranker 仍为 Qwen3-Reranker。
2. **第二批**：将精排模型替换为 `BAAI/bge-reranker-v2-m3`，保持 `/v1/rerank` 入参出参不变，分数继续 0~1 归一化；质量阀门阈值仍按原 Qwen 标定，本批不重标。
3. **第三批**：API 中残留的业务 / 检索编排下沉到 `app.rag.search_app`；切断 `dingtalk_wo_card` 对 `app.api.work_orders._do_transition` 的反向依赖，流转下沉到 `app.domain.work_order_transition`。
4. **第四批（本批）**：收口 Agent/对话记忆写入到 `app.memory.memory_service`，对照 Harness 自检并补充回归用例。不把工单/库存/报价等业务持久化塞进记忆模块。

## 7. 自检清单（修改完成后必须逐条核对）

- [ ] 有没有反向依赖、跨层调用？
- [ ] 对外接口出入参是否兼容？
- [ ] 向量 / 模型调用是否在指定层内？
- [ ] 是否新增未审批的依赖？
- [ ] 原有 case 执行结果是否和修改前一致？

## 8. 记忆门面（第四批）

位置：`backend/app/memory/memory_service.py`（`memory_service` 单例）。

| 层 | 现网落实 | 门面 API | 说明 |
| --- | --- | --- | --- |
| 工作记忆 | 请求期内 scratchpad / 中间态 | `new_scratchpad()` | 不落盘，不新做持久化 |
| 短期会话 | Redis，经存储层 `cache_service`（自动前缀 `maint:`） | `get/set_guided_repair_session`、`get/set_expert_repair_session`、`get/set_mcp_staff_guided_session`、`get/set_mcp_staff_guided_last` | key 前缀与 TTL 与收口前完全一致，见下表 |
| 长期事实 | PostgreSQL | `summarize(messages)` | 现网无独立记忆表，不新造表；摘要计算后写回短期会话 payload。工单/库存/报价等业务表不纳入记忆层 |

短期会话逻辑 key 与 TTL（实际 Redis key = `maint:` + 逻辑 key）：

| 逻辑 key | TTL | 原写入点（现已走门面） |
| --- | --- | --- |
| `guided_repair_session:{session_id}` | 24h（`24 * 3600`） | `guided_repair_agent`，最多 30 步 |
| `expert_repair_session:{session_id}` | 24h | `expert_repair_agent`，最多 30 步 |
| `mcp/staff_guid:session:{staff_id}` | 24h | `mcp/tools.py` 员工会话映射 |
| `mcp/staff_guid:last:{staff_id}` | 24h | 同上，最后活动时间 |

`cache_service` 仍作为存储层 Redis 客户端，并继续服务于用户/配件等**业务缓存**（如 `user:{id}`、`spare_part:{id}`、`stock_alerts:*`），这些不是 Agent 记忆，不收进记忆门面。

多轮追踪维修 / 专家模式仍是 Redis 状态机，不迁到 LangGraph。

## 9. 仍未收口的残留

- 领域层转到 `COMPLETED` 时仍懒加载 `app.api.work_orders.complete_work_order_internal`（domain → API）。
- `app/rag/retrieval_flow.py` 仍依赖 `app.agents.tools.RetrievalTools`（RAG → Agent）。
- 质量阀门阈值仍按原 Qwen3-Reranker 标定，尚未按 `bge-reranker-v2-m3` 重标。
- `dispatch.py` 仍从 `app.api.work_orders` 再导出 shim 取进度日志/工作量辅助函数（API 内部兼容，非 core 反向依赖）。
