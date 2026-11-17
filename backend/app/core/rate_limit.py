"""进程内滑动窗口限流。单进程够用；多副本时各算各的，不替代网关限流。"""
import time
from collections import defaultdict

from fastapi import HTTPException

_hits: dict[str, list[float]] = defaultdict(list)


def hit(key: str, limit: int, window_seconds: float = 60.0) -> None:
    """进程内滑动窗口限流。同一 key 在 window_seconds 内超过 limit 次就抛出 HTTP 429。只适合单进程防护，不能替代网关或 Redis 限流。"""
    now = time.monotonic()
    recent = [stamp for stamp in _hits[key] if now - stamp < window_seconds]
    if len(recent) >= limit:
        _hits[key] = recent
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    recent.append(now)
    _hits[key] = recent
