"""支付只做意向单占位。状态里没有支付成功，也不会调用清算渠道。"""

PAYMENT_STATUSES = ("CREATED", "CANCELLED")
PAYMENT_CHANNEL = "STUB"

PAYMENT_LABELS = {
    "CREATED": "已创建（未清算）",
    "CANCELLED": "已取消",
}
