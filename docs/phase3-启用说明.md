# Phase 3 启用说明

这一阶段在现有门店、工单、报价、备件库存和车主通知上增加四件事：门店数据隔离、交车回访提醒、备件采购入库、第三方只读 MCP。支付仍然只是占位，不接清算。不新增经营指标。

## 数据库

在已经升到 Phase 2（修订号 `f8a9b0c1d2e3`）的库上，于 `backend` 目录执行：

```bash
alembic upgrade head
```

这次的修订号是 `a9b8c7d6e5f4`，可以降回 `f8a9b0c1d2e3`。

空库从零升级时，会先经过更早的迁移。其中 `2a5022bf6eca` 会给 `users.employee_id` 写注释，但前面的迁移没有建这一列，空库会停在这里。这是原有迁移链的问题。工单状态枚举的两次追加改成了 `ADD VALUE IF NOT EXISTS`，避免重复追加把整个迁移事务打断。

新增内容：

- `users.store_id`：店内人员绑定的门店
- `spare_parts.store_id`：备件归属门店，空表示还没分店
- `store_part_stocks`：门店结存
- `stock_movements`：库存流水（采购入库、进货导入、工单领料）
- `purchase_orders`、`purchase_order_lines`
- `follow_up_reminders`
- `work_orders.store_id`、`quotes.store_id` 补索引

`spare_parts.stock_quantity` 仍是仓库总库存。采购入库会同时增加总库存和本店结存，并写一条 `PO_RECEIVE` 流水。

## 门店隔离

管理员不带门店条件时看全部工单、预约、报价和库存。顶栏可以选一家店，选择保存在浏览器里，请求带 `X-Store-Id`，只作为筛选。

主管、维修员、操作工如果用户上写了 `store_id`，只能看这家店。请求里另传门店编号也不会切到别的店。还没绑定门店的店内账号，只能看 `store_id` 为空的历史数据，不能给已分店的单据写入。

给账号绑定门店：

```bash
curl -X PUT "$BASE/api/v1/users/2" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"store_id":1}'

curl "$BASE/api/v1/stores/context" -H "Authorization: Bearer $TOKEN"
```

店内角色的当前门店显示在顶栏，不能切换。管理员的下拉框切换后页面会按所选门店重新加载列表。

## 回访提醒

工单结案（状态到 `CLOSED`）时自动排两条提醒：1 天后邀请评价，7 天后邀请回访。这是排期天数，不是回复率。

发送走 Phase 2 已有的三个出口：阿里云短信、钉钉工作通知、站内通知。开关没打开时短信和钉钉记为 `mock`，内容在日志里，不算发送失败。没有客户档案时记为 `SKIPPED`。

也可以手工排期。到期发送有两个入口：页面上的「发送到期提醒」，以及每 30 分钟跑一次的定时任务（和钉钉审批同步共用现有调度器）。

```bash
curl -X POST "$BASE/api/v1/follow-ups/" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"work_order_id":1,"kind":"RATING"}'

curl -X POST "$BASE/api/v1/follow-ups/dispatch" -H "Authorization: Bearer $TOKEN"
```

`kind` 只能是 `RATING`（评价）或 `REVISIT`（回访）。短信模板仍用 Phase 2 的 `work_order_no` 和 `status`，评价的 status 是「邀请评价」，回访是「邀请回访」。

## 采购入库

先开采购单，再入库。入库才会增加备件总库存和该店结存。编码还不存在时，入库会按采购行新建备件，并标上这家店。

```bash
curl -X POST "$BASE/api/v1/purchase-orders/" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"store_id":1,"supplier":"本地汽配","lines":[{"part_code":"BP-1","part_name":"前刹车片","qty":4,"unit_price":180}]}'

curl -X POST "$BASE/api/v1/purchase-orders/1/receive" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{}'
```

不传明细时，把未收数量一次收完。已有入库数量的单不能取消。批量导入接口 `/api/v1/spare-parts/import` 仍可用，多了一个可选的 `store_id`，导入时同样写库存流水。

页面在「采购入库」。

## 只读 MCP

内部 `/mcp` 维持原来的访问方式：配置了 `MCP_API_KEY` 就校验 Key，没配置时只允许本机。写工具 `draft_quote` 和 `guided_repair_chat` 默认不挂到 HTTP。钉钉机器人仍然直接调用 `app/mcp/tools.py`，不经过这个开关。

要在内部入口打开写工具：

```bash
MCP_ENABLE_WRITE_TOOLS=true
```

第三方用 `/mcp/public`。这个入口默认开启，且必须带凭证，本机匿名也不行。只挂这些只读工具：

- `query_work_order`
- `query_compatible_parts`
- `recommend_service`
- `query_inventory`
- `get_workorder_stats`

凭证二选一：

- `Authorization: Bearer $MCP_API_KEY`
- 现有登录 JWT。令牌没有 `scope` 时按只读放行；如果写了 `scope`，必须包含 `mcp:read`

```bash
MCP_PUBLIC_ENABLED=true
MCP_API_KEY=换成你自己的密钥

curl -X POST "$BASE/mcp/public" \
  -H "Authorization: Bearer $MCP_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

`MCP_PUBLIC_ENABLED=false` 时公开入口返回 404。

## 本地核对

```bash
cd backend && alembic upgrade head
cd backend && pytest tests/test_phase3_platform.py tests/test_phase2_commerce.py tests/test_phase1_loop.py tests/test_phase0_domain.py -q
cd frontend && npm run build
```

接口抽查（先登录拿 `$TOKEN`，`$BASE` 默认 `http://127.0.0.1:18080`）：

```bash
curl "$BASE/api/v1/stores/context" -H "Authorization: Bearer $TOKEN"
curl "$BASE/api/v1/work-orders/?store_id=1" -H "Authorization: Bearer $TOKEN"
curl "$BASE/api/v1/follow-ups/" -H "Authorization: Bearer $TOKEN"
curl "$BASE/api/v1/purchase-orders/" -H "Authorization: Bearer $TOKEN"
```
