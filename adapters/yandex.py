"""Адаптер Yandex Market: поиск товаров по названию.

Использует официальное публичное API Yandex Market
(https://api.content.market.yandex.ru/v2/models) — бесплатное, но требует
API-ключ (выдаётся в кабинете разработчика Yandex). Ключ передаётся в
заголовке Authorization без префикса Bearer.

Без ключа API отвечает HTTP 401 — адаптер возвращает пустую выдачу и
логирует предупреждение (бот продолжает работать с остальными площадками).
Цены в ответе — числа в рублях с дробной частью ("value": 5499.0) —
округляются до целых рублей.
"""
from __future__ import annotations

import json
import logging
import zlib

from adapters.base import BaseAdapter
from models import Product

logger = logging.getLogger(__name__)

SEARCH_API_URL = "https://api.content.market.yandex.ru/v2/models"


class YandexAdapter(BaseAdapter):
    """Поиск по Yandex Market через официальное публичное API (по ключу)."""

    name = "yandex"

    def __init__(self, api_key: str = "", region_id: int = 213, transport=None,
                 max_retries: int | None = None) -> None:
        super().__init__(transport=transport, max_retries=max_retries)
        self._api_key = api_key
        self._region_id = region_id

    async def search(self, query: str, limit: int = 5) -> list[Product]:
        if not self._api_key:
            logger.warning(
                "MARKET_YANDEX_API_KEY не задан — Yandex Market пропущен. "
                "Ключ выдаётся бесплатно в кабинете разработчика Yandex."
            )
            return []
        params = {"query": query, "regionId": self._region_id}
        extra_headers = {"Authorization": self._api_key}
        status, text = await self._get(SEARCH_API_URL, params=params, extra_headers=extra_headers)
        if status == 401:
            logger.warning("Yandex Market -> HTTP 401: ключ недействителен")
            return []
        if status != 200:
            logger.warning("Yandex Market -> HTTP %s для запроса %r", status, query)
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Yandex Market вернул не-JSON для запроса %r", query)
            return []
        items = data.get("items") or []
        return [p for p in (self.parse_product(i) for i in items[:limit]) if p is not None]

    @staticmethod
    def parse_product(raw: dict) -> Product | None:
        """Сырой товар Yandex Market -> Product (цены округляются до рублей)."""
        pid = raw.get("id")
        if pid is None:
            return None
        prices = raw.get("prices") or {}
        price = prices.get("value")
        old_price = prices.get("oldValue") or (prices.get("discount") or {}).get("oldValue")
        link = raw.get("link") or f"https://market.yandex.ru/product/{pid}/"
        return Product(
            marketplace="yandex",
            ext_id=str(pid),
            title=str(raw.get("name") or "—"),
            price=int(round(price)) if isinstance(price, (int, float)) else 0,
            old_price=int(round(old_price)) if isinstance(old_price, (int, float)) else None,
            url=str(link),
            stock=None,  # публичное API не отдаёт остатки
            rating=raw.get("rating"),
        )


class MockYandexAdapter:
    """Демо-режим: детерминированная выдуманная выдача по запросу."""

    name = "yandex"

    async def search(self, query: str, limit: int = 5) -> list[Product]:
        seed = zlib.crc32(query.lower().encode("utf-8")) % 100
        base = 5200 + (seed * 17) % 2500
        return [
            Product(
                marketplace="yandex",
                ext_id=f"ya-{seed}-{i}",
                title=f"{query.title()} — вариант {i + 1} (Яндекс Маркет, mock)",
                price=base + i * 180,
                old_price=base + i * 180 + 1000,
                url=f"https://market.yandex.ru/product/{seed}{i}/",
                stock=None,
                rating=round(4.2 + (seed % 8) / 10, 1),
            )
            for i in range(limit)
        ]

    async def aclose(self) -> None:
        return None
