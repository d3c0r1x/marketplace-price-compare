"""Middlewares aiogram v3: троттлинг и логирование.

Троттлинг защищает от спама: сообщения чаще, чем раз в min_interval секунд,
молча дропаются. Логирование замеряет время обработки каждого апдейта.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

logger = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    """Ограничивает частоту сообщений от одного пользователя."""

    def __init__(self, min_interval: float = 0.7, burst: int = 3) -> None:
        self._min_interval = min_interval
        self._burst = burst
        self._last: dict[int, float] = {}
        self._streak: dict[int, int] = defaultdict(int)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = getattr(getattr(event, "from_user", None), "id", None)
        if user_id is not None:
            now = time.monotonic()
            last = self._last.get(user_id)
            if last is not None and now - last < self._min_interval:
                self._streak[user_id] += 1
                if self._streak[user_id] >= self._burst:
                    logger.warning(
                        "Throttle: пользователь %s шлёт сообщения чаще, чем раз в %.1fs",
                        user_id, self._min_interval,
                    )
                return None  # молча дропаем
            self._last[user_id] = now
            self._streak[user_id] = 0
        return await handler(event, data)


class LoggingMiddleware(BaseMiddleware):
    """Замеряет и пишет в лог время обработки каждого апдейта."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        start = time.perf_counter()
        result = await handler(event, data)
        elapsed_ms = (time.perf_counter() - start) * 1000
        user_id = getattr(getattr(event, "from_user", None), "id", None)
        logger.info(
            "Обработка %s (user=%s): %.1f мс",
            type(event).__name__, user_id, elapsed_ms,
        )
        return result
