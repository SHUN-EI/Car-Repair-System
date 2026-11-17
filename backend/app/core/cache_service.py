"""Redis 缓存服务

提供带过期时间的键值缓存，用于：
- 库存查询结果缓存
- 用户信息缓存
- 高频读操作缓存
- 分布式锁基础
"""
import json
import time
import hashlib
from typing import Optional, Any, Callable, TypeVar, Dict
from functools import wraps
from loguru import logger

from app.core.config import settings

T = TypeVar("T")

try:
    import redis
    _redis_available = True
except ImportError:
    _redis_available = False
    logger.warning("[Cache] redis-py 未安装，缓存将使用内存字典")


class CacheService:
    """缓存服务"""

    def __init__(self):
        """初始化缓存服务：默认键前缀为 maint:，默认 TTL 300 秒。Redis 客户端延迟到第一次使用再连接，连不上时回退到进程内字典。"""
        self._client = None
        self._memory_store: Dict[str, tuple] = {}
        self._prefix = "maint:"
        self._default_ttl = 300
        self._enabled = True

    @property
    def client(self):
        """惰性获取 Redis 客户端。首次调用时按配置连接并 ping；失败则记下警告并返回 None，后续读写会走内存缓存。"""
        if self._client is None and _redis_available and self._enabled:
            try:
                self._client = redis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=2,
                )
                self._client.ping()
                logger.info("[Cache] Redis 连接成功")
            except Exception as e:
                logger.warning(f"[Cache] Redis 连接失败: {e}，使用内存缓存")
                self._client = None
        return self._client

    def _make_key(self, key: str) -> str:
        """给业务键加上 maint: 前缀，避免和 Redis 里其它系统的键冲突。调用方传入的逻辑键不要自己再加这个前缀。"""
        return f"{self._prefix}{key}"

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        full_key = self._make_key(key)

        client = self.client
        if client:
            try:
                data = client.get(full_key)
                if data is None:
                    return None
                return json.loads(data)
            except Exception as e:
                logger.warning(f"[Cache] Redis GET 失败: {e}")
                return self._memory_get(full_key)

        return self._memory_get(full_key)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置缓存"""
        full_key = self._make_key(key)
        ttl = ttl or self._default_ttl

        try:
            serialized = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            serialized = str(value)

        client = self.client
        if client:
            try:
                client.setex(full_key, ttl, serialized)
                return True
            except Exception as e:
                logger.warning(f"[Cache] Redis SET 失败: {e}")
                return self._memory_set(full_key, value, ttl)

        return self._memory_set(full_key, value, ttl)

    def delete(self, key: str) -> bool:
        """删除缓存"""
        full_key = self._make_key(key)

        client = self.client
        if client:
            try:
                client.delete(full_key)
            except Exception as e:
                logger.warning(f"[Cache] Redis DELETE 失败: {e}")

        self._memory_delete(full_key)
        return True

    def invalidate_pattern(self, pattern: str) -> int:
        """按模式删除缓存"""
        count = 0
        full_pattern = self._make_key(pattern)

        client = self.client
        if client:
            try:
                cursor = 0
                while True:
                    cursor, keys = client.scan(cursor, match=full_pattern, count=100)
                    if keys:
                        client.delete(*keys)
                        count += len(keys)
                    if cursor == 0:
                        break
            except Exception as e:
                logger.warning(f"[Cache] 模式删除失败: {e}")

        return count

    def _memory_get(self, key: str) -> Optional[Any]:
        """从进程内兜底字典读取缓存。键不存在或已过期时删除并返回 None。"""
        if key not in self._memory_store:
            return None
        value, expire_at = self._memory_store[key]
        if expire_at and time.time() > expire_at:
            del self._memory_store[key]
            return None
        return value

    def _memory_set(self, key: str, value: Any, ttl: int) -> bool:
        """把值写入进程内兜底字典，并按 TTL 计算过期时间。"""
        expire_at = time.time() + ttl
        self._memory_store[key] = (value, expire_at)
        return True

    def _memory_delete(self, key: str):
        """从进程内兜底字典删除指定键，键不存在时忽略。"""
        self._memory_store.pop(key, None)

    def memoize(self, ttl: Optional[int] = None, key_func: Optional[Callable] = None):
        """缓存装饰器"""
        def decorator(func: Callable) -> Callable:
            """包一层函数缓存：按自定义 key 函数或参数哈希查找，命中则直接返回；未命中则执行原函数并把结果按 TTL 写入缓存。"""
            @wraps(func)
            def wrapper(*args, **kwargs):
                """实际挂到原函数上的包装器：先查缓存，没有再执行原函数并把结果写入缓存。"""
                if key_func:
                    cache_key = key_func(*args, **kwargs)
                else:
                    key_str = f"{func.__module__}.{func.__name__}"
                    arg_str = ":".join([str(a)[:50] for a in args])
                    kw_str = ":".join([f"{k}={str(v)[:30]}" for k, v in sorted(kwargs.items())])
                    hash_input = f"{key_str}|{arg_str}|{kw_str}"
                    cache_key = hashlib.md5(hash_input.encode()).hexdigest()

                cached = self.get(cache_key)
                if cached is not None:
                    logger.debug(f"[Cache] HIT: {func.__name__}")
                    return cached

                result = func(*args, **kwargs)
                self.set(cache_key, result, ttl=ttl)
                logger.debug(f"[Cache] MISS: {func.__name__}")
                return result

            return wrapper
        return decorator


cache_service = CacheService()