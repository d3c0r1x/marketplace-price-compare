"""Адаптер Wildberries: поиск товаров по названию.

Использует публичный эндпоинт search.wb.ru (как в Проекте 1). Цены WB
приходят в КОПЕЙКАХ (priceU / salePriceU) — делим на 100. С заблокированного
IP эдж отдаёт HTTP 429/403 или «фейковую» пустоту с кодом 200 — в этих
случаях адаптер возвращает пустую выдачу, а не падает.
"""
from __future__ import annotations

import json
import logging
import zlib

from adapters.base import BROWSER_HEADERS, BaseAdapter
from models import Product

logger = logging.getLogger(__name__)

SEARCH_API_URL = "https://search.wb.ru/exactmatch/ru/common/v4/search"

DEFAULT_PARAMS = {
    "appType": "1",
    "curr": "rub",
    "dest": "-1257786",
    "spp": "30",
}

class WbAdapter(BaseAdapter):
    """Поиск по Wildberries через публичный API поиска."""

    name = "wb"
    # Заголовки WB: сайт wildberries.ru (Origin same-site для search.wb.ru)
    headers = {
        **BROWSER_HEADERS,
        "Referer": "https://www.wildberries.ru/",
        "Origin": "https://www.wildberries.ru",
    }

    async def search(self, query: str, limit: int = 5) -> list[Product]:
        params = {
            **DEFAULT_PARAMS,
            "query": query,
            "resultset": "catalog",
            "sort": "popular",
            "page": "1",
        }
        status, text = await self._get(SEARCH_API_URL, params=params)
        if status != 200:
            logger.warning("search.wb.ru -> HTTP %s для запроса %r", status, query)
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("search.wb.ru вернул не-JSON для запроса %r", query)
            return []
        products = (data.get("data") or {}).get("products") or []
        return [p for p in (self._parse(p) for p in products[:limit]) if p is not None]

    @staticmethod
    def parse_product(raw: dict) -> Product | None:
        """Сырой товар WB -> Product (цены из копеек в рубли)."""
        pid = raw.get("id")
        if pid is None:
            return None
        price_u = int(raw.get("priceU", 0) or 0)
        sale_price_u = int(raw.get("salePriceU", price_u) or price_u)
        return Product(
            marketplace="wb",
            ext_id=str(pid),
            title=str(raw.get("name") or "—"),
            price=sale_price_u // 100,
            old_price=(price_u // 100) if price_u else None,
            url=f"https://www.wildberries.ru/catalog/{pid}/detail.aspx",
            stock=int(raw.get("qty", 0) or 0) or None,
            rating=raw.get("rating"),
        )

    _parse = parse_product


class MockWbAdapter:
    """Демо-режим: детерминированная выдуманная выдача по запросу."""

    name = "wb"

    async def search(self, query: str, limit: int = 5) -> list[Product]:
        # zlib.crc32 вместо hash(): хэш строк рандомизируется между процессами
        seed = zlib.crc32(query.lower().encode("utf-8")) % 100
        base = 5000 + seed * 37
        return [
            Product(
                marketplace="wb",
                ext_id=f"wb-{seed}-{i}",
                title=f"{query.title()} — вариант {i + 1} (WB, mock)",
                price=base + i * 250,
                old_price=base + i * 250 + 1500,
                url=f"https://www.wildberries.ru/catalog/{seed}{i}/detail.aspx",
                stock=(seed + i * 3) % 40,
                rating=round(4.0 + (seed % 10) / 10, 1),
            )
            for i in range(limit)
        ]

    async def aclose(self) -> None:
        return None
