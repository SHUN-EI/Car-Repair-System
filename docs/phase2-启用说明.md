# Phase 2 启用说明

这一阶段在现有门店工单上增加适配配件、保养套餐、报价草案、车主通知和支付占位。支付没有清算，微信也没有新渠道。通知只复用阿里云短信和钉钉工作通知。

车辆品牌对应备件规则里的 `brand`，车辆车型对应 `series`。发动机不在车辆档案上，查询时单独传 `engine`。规则里留空的字段表示这一维不限制；一条规则全部留空表示不限车型。没有规则的备件不会出现在适配结果里。

## 数据库

在 `backend` 目录执行：

```bash
alembic upgrade head
```

新增内容：

- `spare_parts.fitment`
- `service_packages`、`service_skus`
- `quotes`、`quote_lines`
- `payment_intents`，状态只有 `CREATED` 和 `CANCELLED`

## 适配查询

先给备件写规则，再按车型查。

```bash
curl -X PUT "$BASE/api/v1/spare-parts/1" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"fitment":[{"brand":"大众","series":"速腾","year_from":2016,"year_to":2020,"engine":"1.4T"}]}'

curl "$BASE/api/v1/spare-parts/compatible?brand=大众&series=速腾&year=2018&engine=1.4T" \
  -H "Authorization: Bearer $TOKEN"
```

也可以传 `vehicle_id` 或 `plate`。库存问答里如果包含「适配」或「适用」，会走同一套规则，不再走原来的关键词库存回答。MCP 工具名是 `query_compatible_parts`。

## 保养套餐

页面在「保养套餐」。推荐接口不调用模型，只按品牌、车系、里程和症状关键词排序。里程不传时，不按里程区间过滤。

```bash
curl -X POST "$BASE/api/v1/service-packages/" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"code":"PKG-OIL","name":"小保养","brand":"大众","series":"速腾","mileage_from":8000,"mileage_to":12000,"symptom_keywords":["机油"],"list_price":399}'

curl -X POST "$BASE/api/v1/service-packages/recommend" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"brand":"大众","series":"速腾","mileage":10000,"symptoms":"该换机油了"}'
```

MCP 工具名是 `recommend_service`。`mileage` 传 `-1` 表示未知里程。

## 报价

门店工单详情里可以按领料、问诊文本或保养套餐生成草案。顺序是：草案 → 店员确认 → 车主确认。车主确认前不能创建支付占位。

店员确认和工单上的「确认报价」权限一样，只有主管或管理员。车主在进度页确认自己的报价；主管可以代录，请求体带 `{"on_behalf": true}`。

```bash
curl -X POST "$BASE/api/v1/quotes/draft" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"work_order_id":1,"include_used_parts":true}'

curl -X POST "$BASE/api/v1/quotes/1/staff-confirm" -H "Authorization: Bearer $TOKEN"
curl -X POST "$BASE/api/v1/quotes/1/customer-confirm" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}'
```

问诊文本里如果写的是「知识库未给出可执行项目」，不会编出报价明细。目录里没有价格的项目单价记 0，由店员在草案上改。MCP 工具名是 `draft_quote`，它只生成草案。

## 车主通知

工单状态变更，以及报价的店员确认、车主确认、拒绝，会通知报价或工单上的客户。没有客户档案时跳过。

三个出口：

| 出口 | 何时发出 | 怎么打开 |
| --- | --- | --- |
| 短信 | 客户有手机号 | 见下方阿里云 |
| 钉钉工作通知 | 客户关联的系统用户填了 `dingtalk_userid` | 见下方钉钉 |
| 站内通知 | 客户关联了系统用户 | 自动写入现有通知表 |

返回值里 `sms` / `dingtalk` 会是 `sent`、`mock`、`skipped` 或 `failed`。`mock` 表示开关没打开，内容只留在后端日志，没有打到外部。

### 阿里云短信

沿用 `app/core/sms.py`，不新增供应商。验证码模板和状态通知模板分开。

```bash
SMS_ENABLED=true
SMS_ACCESS_KEY_ID=你的 AccessKey
SMS_ACCESS_KEY_SECRET=你的 Secret
SMS_SIGN_NAME=已审核签名
SMS_NOTICE_TEMPLATE_CODE=SMS_xxxxxx
```

通知模板变量名固定为 `work_order_no` 和 `status`，例如：`您的工单${work_order_no}当前进度：${status}`。

`SMS_ENABLED=false` 时不会请求阿里云，后端会打印「车主状态短信」。不要把状态通知配进 `SMS_TEMPLATE_CODE`，那个模板只给验证码用。

### 钉钉

沿用现有企业内部应用和工作通知，不新增机器人。

1. `DINGTALK_APP_KEY`、`DINGTALK_APP_SECRET`、`DINGTALK_AGENT_ID` 配好。
2. 把车主的系统用户绑上 `dingtalk_userid`。客户档案的 `user_id` 指向这个用户。
3. 真实发送时设 `DINGTALK_MOCK_MODE=false`。默认是 `true`，此时只打日志，返回 `dingtalk=mock`。

没有绑定钉钉的车主不会收到钉钉消息，短信和站内通知仍按各自条件发送。

## 支付占位

只在车主已确认的报价上创建意向单。金额等于报价合计。渠道固定 `STUB`。没有支付成功状态，也没有回调。

```bash
curl -X POST "$BASE/api/v1/payments/intents/" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"quote_id":1}'

curl -X POST "$BASE/api/v1/payments/intents/1/cancel" -H "Authorization: Bearer $TOKEN"
```

同一张报价如果已经有未取消的意向单，再次创建会返回原来的单，`reused` 为 true。

## 本地核对

```bash
cd backend && pytest tests/test_phase2_commerce.py tests/test_phase1_loop.py tests/test_phase0_domain.py -q
cd frontend && npm run build
```
