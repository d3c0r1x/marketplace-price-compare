"""Продвинутые утилиты на чистом stdlib: TTL-кэш и retry с джиттером."""
from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TTLCache:
    """Простейший TTL-кэш: значение живёт ttl секунд после записи."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self._ttl = ttl_seconds
        self._store: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        item = self._store.get(key)
        if item is None:
            return None
        expires, value = item
        if time.monotonic() > expires:
            self._store.pop(key, None)
            return None
        return value

    async def get_or_set(self, key: Any, factory: Callable[[], Awaitable[T]]) -> T:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = await factory()
        self._store[key] = (time.monotonic() + self._ttl, value)
        return value

    def invalidate(self, key: Any | None = None) -> None:
        if key is None:
            self._store.clear()
        else:
            self._store.pop(key, None)

    @property
    def size(self) -> int:
        return len(self._store)


def backoff(attempt: int, base: float = 0.5, max_delay: float = 10.0, jitter: float = 0.3) -> float:
    """Экспоненциальный backoff с джиттером: base * 2^(attempt-1), ±jitter%."""
    delay = min(base * (2 ** (attempt - 1)), max_delay)
    return delay * (1 + random.uniform(-jitter, jitter))


def async_retry(
    retries: int = 3,
    base: float = 0.5,
    retry_on: tuple[type[Exception], ...] = (Exception,),
):
    """Декоратор для асинхронных функций: повторы с экспоненциальным backoff."""

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last: Exception | None = None
            for attempt in range(1, retries + 1):
                try:
                    return await func(*args, **kwargs)
                except retry_on as exc:
                    last = exc
                    if attempt == retries:
                        break
                    delay = backoff(attempt, base=base)
                    logger.debug(
                        "%s: попытка %d/%d не удалась (%s), повтор через %.1fs",
                        func.__name__, attempt, retries, exc, delay,
                    )
                    await asyncio.sleep(delay)
            assert last is not None
            raise last

        return wrapper

    return decorator
