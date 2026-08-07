"""Общая HTTP-обвязка адаптеров: транспорты httpx/curl_cffi, retry, заголовки.

Транспорты и логика повторов общие для всех маркетплейсов — по одному клиенту на
маркетплейс, чтобы не дублировать код. Антибот-ситуация описана в README:
оба публичных API защищены, поэтому предусмотрен прокси и демо-режим.
"""
from __future__ import annotations

import asyncio
import logging

import config

logger = logging.getLogger(__name__)

# Заголовки «как у браузера». User-Agent при curl_cffi выставляет имитация
# Chrome (ручной UA сломал бы отпечаток).
BROWSER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

_RETRY_STATUSES = {429, *range(500, 600)}


def _backoff(attempt: int, min_delay: float = 0.5) -> float:
    """Экспоненциальная задержка: 0.5, 1.0, 2.0 … (потолок 10 c)."""
    return min(min_delay * (2 ** (attempt - 1)), 10.0)


try:
    from curl_cffi.requests import AsyncSession as CurlCffiSession

    HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover
    CurlCffiSession = None
    HAS_CURL_CFFI = False


class HttpxTransport:
    """Транспорт на httpx (без имитации отпечатка)."""

    def __init__(self, timeout: float = 20.0, proxy: str = "") -> None:
        import httpx

        self._client = httpx.AsyncClient(timeout=timeout, proxy=proxy or None)

    async def get(self, url: str, *, params=None, headers=None) -> tuple[int, str]:
        resp = await self._client.get(url, params=params, headers=headers)
        return resp.status_code, resp.text

    async def aclose(self) -> None:
        await self._client.aclose()


class CurlCffiTransport:
    """Транспорт на curl_cffi: имитация TLS/HTTP2-отпечатка Chrome."""

    def __init__(
        self,
        timeout: float = 20.0,
        impersonate: str = "chrome",
        proxies: dict | None = None,
    ) -> None:
        self._session = CurlCffiSession(
            impersonate=impersonate,
            timeout=timeout,
            proxies=proxies,
        )

    async def get(self, url: str, *, params=None, headers=None) -> tuple[int, str]:
        resp = await self._session.get(
            url, params=params, headers=headers, allow_redirects=False
        )
        return resp.status_code, resp.text

    async def aclose(self) -> None:
        closer = getattr(self._session, "aclose", None) or self._session.close
        await closer()


def _make_transport() -> HttpxTransport | CurlCffiTransport:
    """Выбирает транспорт по MARKET_HTTP_CLIENT (curl_cffi по умолчанию)."""
    if config.HTTP_CLIENT == "curl_cffi":
        if not HAS_CURL_CFFI:
            logger.warning(
                "MARKET_HTTP_CLIENT=curl_cffi, но библиотека не установлена. "
                "Падаем обратно на httpx. Установите: pip install curl_cffi"
            )
        else:
            proxies = None
            if config.PROXY:
                proxies = {"http": config.PROXY, "https": config.PROXY}
            return CurlCffiTransport(proxies=proxies)
    return HttpxTransport(proxy=config.PROXY)


class BaseAdapter:
    """Базовый HTTP-адаптер: GET с retry на 429/5xx и сетевые ошибки."""

    name = "base"
    # Заголовки по умолчанию; адаптеры переопределяют (см. wb.py/ozon.py),
    # добавляя специфичные для маркетплейса (Referer, Origin, x-o3-app-name).
    headers = BROWSER_HEADERS

    def __init__(self, transport=None, max_retries: int | None = None) -> None:
        self._transport = transport if transport is not None else _make_transport()
        self._max_retries = max_retries if max_retries is not None else config.MAX_RETRIES

    async def _get(self, url: str, *, params=None, retries: int | None = None,
               extra_headers: dict | None = None) -> tuple[int, str]:
        max_retries = self._max_retries if retries is None else retries
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                status, text = await self._transport.get(
                    url, params=params, headers={**self.headers, **(extra_headers or {})}
                )
            except Exception as exc:
                last_exc = exc
                if attempt == max_retries:
                    raise
                await asyncio.sleep(_backoff(attempt))
                continue
            if status in _RETRY_STATUSES and attempt < max_retries:
                await asyncio.sleep(_backoff(attempt))
                continue
            return status, text
        raise last_exc if last_exc is not None else RuntimeError("unreachable")

    async def search(self, query: str, limit: int = 5) -> list:
        """Поиск товаров по запросу. Возвращает список Product."""
        raise NotImplementedError

    async def aclose(self) -> None:
        await self._transport.aclose()
