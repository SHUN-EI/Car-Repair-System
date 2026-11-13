"""Agent 记忆层：工作记忆、短期 Redis 会话、长期事实入口。

外部读写统一走 app.memory.memory_service，不要在调用方拼 Redis key 或设 TTL。
cache_service 仍作为存储层 Redis 客户端，也继续服务库存/用户等业务缓存。
"""
