# 汽修 Agent 平台改造方案

> 完整交互版 Page：[汽修 Agent 平台改造方案](https://cursor.com/canvas/store-43fbe953-ceec-47c3-af70-105eda1218a1/4839ba78-2871-467b-9658-fa61d77a51c8)  
> 同目录：[代码完善清单](./代码完善清单.md)、[开源模型后训练技术方案](./开源模型后训练技术方案.md)、[Phase 2 启用说明](./phase2-启用说明.md)、[Phase 3 启用说明](./phase3-启用说明.md)  
> 依据：Smart-Repair-System / Car-Repair-System 现有代码 + 技术梳理；**文档冲突采信代码**。本文没有被覆盖重写，只补了互链。

## 一句话定位

把制造设备维修数字化平台，改造成车主端 + 门店端 + 技师端的汽修 Agent 平台；先做门店数字化与智能问诊/知识，再做配件匹配与预约履约，供应链后置。对标公开可见的「途虎类」能力形态（线上选品/预约 + 线下门店履约），定位中小连锁/单店可落地，不复刻全国供应链。

---

## 1. 目标与边界

改造起点：FastAPI + Vue3 + LangGraph + PG/Redis/Milvus + DeepSeek + bge-m3。目标是可运营的单店/少量门店汽修 Agent 平台，而不是全国加盟 SaaS 或自建仓配。

### 对标的公开能力形态（非官方商标/内部 API）

- **车主侧**：选车/绑车档案；保养项目与套餐浏览；预约门店时段；透明报价草案与工单进度
- **门店侧**：维保工单与派工；备件库存与出入库；客户/车辆档案；驾驶舱报表
- **技师侧**：接单队列；施工进度回写；现场问诊/手册检索
- **Agent 侧**：故障问诊；保养建议；配件推荐（基于 fitment）；知识/手册/案例检索

### 一期明确不做

- 全国加盟/多租户 SaaS 运营后台
- 汽配龙级 B2B 采购撮合与开放目录
- 自建全国仓配与干线物流
- 完整社区电商/内容带货
- 编造途虎未公开的内部 API、库存同步协议或 KPI

### MVP 边界

Phase 0–1 只交付「门店工单闭环 + 车主 H5 预约/进度 + 汽修语料 RAG 问诊」。支付、微信生态、多门店、采购进销存放在 P1/P2，且支付仅做接口占位。

---

## 2. 领域映射表

改造动作三类：复用 / 改名扩展 / 新建。

| 途虎类能力 | Smart-Repair 现有模块 | 改造动作 | 优先级 |
| --- | --- | --- | --- |
| 车辆档案 | `models/device.py` + `api/devices` + `Devices.vue`/`DeviceForm.vue` | 改名扩展 → Vehicle（车牌/VIN/车型/里程） | P0 |
| 维保工单 | `models/work_order.py` + `api/work_orders` + `WorkOrders.vue` | 改名扩展：状态机改预约→交车 | P0 |
| 知识/案例检索 | `models/knowledge.py` + `api/knowledge` + `agents/retrieval_flow.py` | 复用检索管线；语料换汽修案例 | P0 |
| 手册/故障码 | `models/manual_code.py` + `fault_code.py` + `ManualCodes.vue` | 改名扩展：OEM 手册码 + OBD/故障灯 | P0 |
| 备件库存 | `models/spare_part.py` + `api/spare-parts` + `SpareParts.vue`/`Warehouse.vue` | 改名扩展：加车型 fitment | P0/P1 |
| 派工 | `api/dispatch` + `SupervisorDispatch.vue` | 复用；绑定技师/工位 | P0 |
| 排班请假 | `duty_schedule`/`leave_request` + `SupervisorSchedule.vue` | 复用；映射门店技师班次 | P1 |
| 钉钉/IM 协作 | `core/dingtalk*` + `agents/robot_graph.py` + `/api/v1/dingtalk` | 复用门店侧；车主侧另接短信/微信可选 | P0/P1 |
| AI 问答 SSE | `api/search` + `qa_graph.py` + `AiAssistant.vue`/`Search.vue` | 复用；话术与工具改汽修 | P0 |
| 引导/专家多轮 | `guided_repair_agent.py` + `expert_repair_agent.py` + Redis session | 改名扩展：症状→项目→预约 | P0 |
| 驾驶舱 | `api/dashboard` + `Dashboard.vue` | 改名扩展：预约/完工/产值指标占位 | P1 |
| 用户角色 | `models/user.py` + `api/users`/`auth` | 改名扩展：车主/店长/技师/仓管 | P0 |
| 历史导入沉淀 | `work_order_importer.py` + `api/work-order-imports` | 复用 PDF/工单导入；补 `pdfplumber` 依赖 | P1 |
| 保养套餐/SKU | 无对等模型（仅有 Category） | 新建 ServiceSKU / Package | P1 |
| 预约槽位 | 无 | 新建 Appointment + 工位 Bay | P0 |
| 报价单 | 无（工单字段可部分承载） | 新建 Quote；草案可由 Agent 生成 | P1 |
| 客户档案 | 部分落在 User；无独立 Customer | 新建 Customer，关联 Vehicle | P0 |
| 门店 | 无多门店实体 | 新建 Store（单店先一条记录） | P0 |
| MCP 对外工具 | `app/mcp/server.py` | 改名扩展工具清单；P2 对外开放 | P1/P2 |

---

## 3. 目标架构

节点对齐现网技术栈：FastAPI、Vue3、LangGraph、Milvus、DeepSeek、bge-m3、Redis、PostgreSQL。支付与微信标为可选。

```
车主端 H5 ──┐
门店端 PC ──┼── FastAPI (/api/v1 + SSE + /mcp)
技师端 ─────┘         │
                      ├── Agent 编排 (qa_graph / guided / expert / retrieval_flow)
                      │         ├── 检索与知识 (bge-m3 + bge-reranker-v2-m3 + RRF)
                      │         └── DeepSeek 生成
                      ├── PG + Redis + Milvus
                      ├── 消息（钉钉 + 短信开关）
                      └── 支付（可选，P1 占位）
```

原则沿用 SRS：管道优先、ReAct 仅救援；检索数据走本地 embedding/Milvus；生成走云端 DeepSeek；门店协作优先复用钉钉 Stream/卡片。

---

## 4. 数据模型改造

1. **Device → Vehicle**  
   保留 devices 表或迁移为 vehicles：`plate_no`、`vin`、`brand`、`series`、`model_year`、`mileage`、`last_service_at`；废弃/降级 `run_status` 或改为车况标签。入口：`backend/app/models/device.py`、`api/devices.py`、`Devices.vue`。

2. **WorkOrder 状态机（维保）**  
   现枚举含 DRAFT/SUBMITTED/ASSIGNED/ACCEPTED/ARRIVED/INSPECTING/IN_PROGRESS/COMPLETED/ARCHIVING/REJECTED 及旧态。建议映射：`APPOINTMENT_BOOKED → CHECKED_IN → DIAGNOSING → IN_SERVICE → QC → DELIVERED → ARCHIVED`；Alembic 做值映射 + 兼容读旧值。

3. **新建核心表**  
   Customer、Store、Bay、Appointment、ServiceSKU/ServicePackage、Quote/QuoteLine；SparePart 增加 `fitment`（JSONB：年款/车型/排量）。

4. **知识侧拆分**  
   KnowledgeItem 用 category/标签区分案例 / OEM 手册 / 保养规范；ManualCodeEntry 面向 OBD/故障灯；FaultCodeMapping 可映射「故障现象→建议项目」。

5. **Alembic 建议顺序**  
   ① Store/Customer/Bay → ② vehicles 改字段或新表+FK 回填 → ③ Appointment/ServiceSKU → ④ WorkOrder 状态迁移 → ⑤ spare_parts.fitment → ⑥ Quote → ⑦ 知识标签回填。每步可回滚；先双写再切读。

| 实体 | 来源 | 关键字段（示意） |
| --- | --- | --- |
| Vehicle | Device 扩展 | plate_no, vin, brand, series, mileage, customer_id |
| Appointment | 新建 | store_id, vehicle_id, slot_start, bay_id, status |
| ServiceSKU | 新建 | code, name, labor_minutes, base_price, package_id |
| Quote | 新建 | work_order_id, lines[], total, customer_confirm |
| SparePart.fitment | 扩展 | [{brand,series,year_from,year_to,engine}] |

---

## 5. Agent 能力设计

检索主干继续复用 `agents/retrieval_flow.py`：四路召回（向量 / ILIKE 加权「BM25」/ 手册精确 / 手册向量）→ RRF(k=60) → 粗筛/精排 → 送 LLM。默认 embedding 仍为代码事实 `BAAI/bge-m3`（1024 维），Reranker `BAAI/bge-reranker-v2-m3`，失败冷却后规则重排。质量阀门阈值仍按原 Qwen3-Reranker 标定，尚未重标。

### 话术与工具改造

- `fault_decomposer.py` / `query_extractor.py`：工业故障分解 → 汽修症状/系统（发动机/底盘/空调等）
- `guided_repair_agent.py`：多轮 Redis 会话改为 症状→可能原因→建议项目→是否预约
- `expert_repair_agent.py`：门店技师深度诊断；质量阀不达标才 ReAct 救援（保持 `AGENT_QUALITY_*` 策略）
- 新建工具（建议 `agents/tools.py` 或 `mcp/tools.py`）：车型解析、保养周期推荐、配件 fitment 查询、报价草案、预约槽位查询/锁定
- `answer_generator.py`：输出结构改为原因说明 + 建议项目 + 风险提示 + 是否建议到店

### MCP 工具清单（现有 → 目标）

| 现有 MCP | 汽修目标 | 阶段 |
| --- | --- | --- |
| `search_knowledge` | 案例/手册/保养规范检索 | P0 |
| `guided_repair_chat` | 车主/技师问诊多轮 | P0 |
| `query_work_order` / `query_my_workorders` | 维保单进度 | P0 |
| `query_inventory` | 配件库存+fitment | P1 |
| `get_device_list` | 改 `get_vehicle_list` | P0 |
| `get_knowledge_stats` / `get_workorder_stats` | 门店运营统计 | P1 |
| （新建）`recommend_service` | 保养周期/套餐 | P1 |
| （新建）`draft_quote` | 报价草案 | P1 |
| （新建）`list_appointment_slots` | 可预约槽位 | P0 |

**策略不变**：管道优先；仅当检索质量不满足「≥3 条且（≥2 条≥0.6 或 max≥0.7）」才启动 `retrieval_agent` ReAct 救援。图上仍不挂 LangGraph RetryPolicy 睡秒级退避。

---

## 6. 分阶段可执行路线

### Phase 0（1–2 周）领域 Renaming + 车辆 MVP

依赖：可运行的现网 compose（PG/Redis/Milvus）与 embedding :8010。

- [ ] Fork/重命名仓库与 README 业务表述（制造→汽修）
- [ ] User 角色扩展：车主/店长/技师/仓管（`models/user.py` + auth）
- [ ] Device→Vehicle 字段迁移与 API/前端路由改名
- [ ] WorkOrder 状态枚举迁移脚本 + 兼容旧值
- [ ] 新建 Store/Customer/Bay/Appointment 最小表
- [ ] 前端：Devices→Vehicles，移动端文案替换

**风险**：状态枚举硬编码散落 API/前端；需全局搜枚举字符串。  
**验收**：能创建车辆档案；能开一张预约态工单并派给技师；旧工单只读不报错。

### Phase 1（3–5 周）P0 门店闭环 + 问诊

- [ ] 门店工单全流程：预约→到店→检测→施工→质检→交车
- [ ] 派工 + 库存出入库（复用 spare_parts / Warehouse）
- [ ] 车主 H5：预约槽位 + 工单进度（扩展 `views/mobile`）
- [ ] 汽修样例语料入库（案例/保养规范/手册码）+ sync_vectors
- [ ] 问诊 Agent SSE（改 guided + search 话术）
- [ ] 钉钉门店侧通知复用（状态变更卡片）

**依赖**：Phase 0 模型稳定；准备 ≥50 条脱敏汽修 QA/案例。  
**风险**：粗筛阈值 0.45 等为工业语料标定，换域后必须重跑 `scripts/calibrate_thresholds.py`（结果【待补充评估】）。  
**验收**：车主可预约并看到进度；店长可派工完工；问诊 SSE 能返回带引用的保养/故障建议（人工抽检即可，无虚构命中率）。

### Phase 2（4–6 周）P1 配件/报价/通知

- [ ] SparePart.fitment + 适配查询工具
- [ ] ServiceSKU/套餐 + Agent 保养推荐
- [ ] Quote 草案生成与店员确认流
- [ ] 短信（已有阿里云开关）/微信或继续钉钉通知车主
- [ ] 支付对接占位（下单意图 API，不接真实清算）

**验收**：给定车型可列出适配配件；问诊结束可生成报价草案；通知可达测试号。支付仅契约测试。

### Phase 3（可选）P2

- [ ] 多门店 Store 切换与数据隔离
- [ ] 评价/回访提醒
- [ ] 进销存采购单
- [ ] MCP 工具对第三方只读开放与鉴权

---

## 7. 技术落地清单

1. **后端模型/API 优先改**
   - `backend/app/models/device.py` → vehicle
   - `backend/app/models/work_order.py` 状态机
   - `backend/app/models/spare_part.py` fitment
   - 新建 models：customer/store/appointment/quote/service_sku
   - `backend/app/api/` 对应路由与 `main.py` include_router
   - `backend/alembic/versions/` 按第 4 节顺序
2. **Agent**
   - `agents/retrieval_flow.py` 阈值重标（保留结构）
   - `agents/guided_repair_agent.py` / `expert_repair_agent.py` 话术
   - `agents/fault_decomposer.py` / `query_extractor.py`
   - `agents/tools.py` + `app/mcp/server.py` 工具
   - `agents/qa_graph.py` 输出 schema
3. **前端**
   - `Devices.vue`/`DeviceForm.vue` → Vehicles
   - `WorkOrders.vue`/`SupervisorDispatch.vue` 状态文案
   - `AiAssistant.vue`/`Search.vue` 问诊
   - `views/mobile/*` 车主预约与技师队列
   - 路由 `frontend/src/router` 改名（**无 Pinia，勿按 README 引入**）
4. **基础设施**
   - embedding 默认仍 `BAAI/bge-m3` + `embedding_server.py` :8010
   - Milvus 集合可继续 knowledge/log_code，或加 auto_manual；维数 1024
   - `requirements.txt` 补齐 `pdfplumber`（及 OCR 可选依赖）
   - 阈值：现网 0.45/0.6/0.3 等仅作起点，换域后【待重标】

---

## 8. 评测与指标

**禁止虚构**：仓库内无固化召回率/QPS/转化率等 KPI。下列一律【代码中无量化指标，待补充评估】。

| 指标 | 定义 | 现状 |
| --- | --- | --- |
| 问诊 Top-k 命中 | 人工标注：前 k 条是否含正确案例/规范 | 【待补充评估】 |
| 预约转化 | 问诊会话 → 成功创建 Appointment | 【待补充评估】 |
| 工单完工时长 | 到店→交车中位/P90 | 【待补充评估】 |
| 配件一次匹配正确率 | fitment 推荐被技师一次采纳 | 【待补充评估】 |
| SSE 首 token/端到端延迟 | P50/P95 | 【待补充评估】 |

### 评测集建设步骤（建议）

1. **场景用例 YAML**：每条含车型、症状/里程、期望项目或知识 id、是否应预约；覆盖保养/故障灯/异响等。
2. **双门槛**：检索门槛（Top-k 命中）+ 任务门槛（是否产出可执行建议/可预约槽位）。
3. **阈值重标定**：跑 `scripts/calibrate_thresholds.py` 看分数分布，再改 `RETRIEVAL_COARSE_THRESHOLD` 等；输出写入评测报告，不写进宣传口径。

---

## 9. 里程碑周次概览

假设 1 名全栈可复用现网（含少量汽修顾问评审语料），日历周仅供排期，非承诺工期。

| 周次 | 焦点 | 产出 |
| --- | --- | --- |
| W1–W2 | Phase 0 | 角色/车辆/状态机/Store·Appointment 骨架 |
| W3–W5 | Phase 1 前半 | 工单闭环 + 派工库存 + 车主预约 H5 |
| W6–W7 | Phase 1 后半 | 汽修语料 + 问诊 SSE + 钉钉通知 |
| W8–W10 | Phase 2 | fitment + 报价草案 + 套餐推荐 + 通知 |
| W11–W12 | 缓冲/P2 预研 | 评测集 v0、支付占位、多门店设计 |

---

## 文档冲突提醒（采信代码）

- 召回默认 **bge-m3**（1024 维）。README 已按代码改为 bge-m3，不再把 Qwen3-Embedding-4B / 4096 维写成现网
- 前端 **无 Pinia**
- 粗筛默认 **0.45**
- 所谓 BM25 为 **PG ILIKE 加权**，不是独立 BM25 引擎

方案执行中勿被 README 旧表述带偏。
