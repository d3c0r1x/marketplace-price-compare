"""Адаптер Ozon: поиск товаров по названию.

Использует публичный composer-api (www.ozon.ru/api/composer-api.bx/page/json/v2,
url=/search/?text=...). Ответ — словарь widgetStates, где каждый виджет это
JSON-строка; товары живут в виджетах с префиксом "webSearchResults".
Структура Ozon нестабильна, поэтому парсер ищет объекты product рекурсивно.

Честный статус: с IP без валидного region-cookie composer-api отдаёт
HTTP 307 (редирект-петля антибота) — адаптер возвращает пустую выдачу;
решение — прокси (MARKET_PROXY) или демо-режим.
"""
from __future__ import annotations

import json
import logging
import zlib

from adapters.base import BROWSER_HEADERS, BaseAdapter
from models import Product

logger = logging.getLogger(__name__)

COMPOSER_API_URL = "https://www.ozon.ru/api/composer-api.bx/page/json/v2"

def _iter_widget_states(data: dict):
    """Итерирует (ключ_виджета, распарсенный_json) из widgetStates."""
    for key, raw in (data.get("widgetStates") or {}).items():
        if not isinstance(raw, str):
            continue
        try:
            yield key, json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue


def _find_products(node, acc: list[dict], depth: int = 0) -> None:
    """Рекурсивно собирает объекты, похожие на товар Ozon (есть id и title)."""
    if depth > 8:
        return
    if isinstance(node, dict):
        if "product" in node and isinstance(node["product"], dict):
            acc.append(node["product"])
        for value in node.values():
            _find_products(value, acc, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _find_products(item, acc, depth + 1)


def _to_rubles(value) -> int | None:
    """Нормализует цену Ozon в целые рубли (строки рублей или копейки)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        value = value.get("value") or value.get("price")
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return int(round(value))
        return value if value < 100000 else value // 100
    s = str(value).replace("\u00a0", " ").replace(" ", "").replace(",", ".").strip()
    if not s or not s.replace(".", "").isdigit():
        return None
    num = float(s)
    if num < 100000 and "." in s and len(s.split(".")[-1]) <= 2:
        return int(round(num))
    if num >= 100000:
        return int(num // 100)
    return int(round(num))


class OzonAdapter(BaseAdapter):
    """Поиск по Ozon через публичный composer-api."""

    name = "ozon"
    # Ozon ожидает заголовок x-o3-app-name (как у приложения/веба)
    headers = {
        **BROWSER_HEADERS,
        "Referer": "https://www.ozon.ru/",
        "Origin": "https://www.ozon.ru",
        "x-o3-app-name": "rich",
    }

    async def search(self, query: str, limit: int = 5) -> list[Product]:
        params = {"url": f"/search/?text={query}"}
        status, text = await self._get(COMPOSER_API_URL, params=params)
        if status == 307:
            logger.warning(
                "Ozon composer-api -> HTTP 307 для запроса %r: регион-блок", query
            )
            return []
        if status != 200:
            logger.warning("Ozon composer-api -> HTTP %s для запроса %r", status, query)
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Ozon composer-api вернул не-JSON для запроса %r", query)
            return []
        return self._parse_response(data, limit)

    def _parse_response(self, data: dict, limit: int) -> list[Product]:
        """Собирает товары из search-виджетов composer-ответа."""
        products: list[Product] = []
        seen: set[str] = set()
        for key, widget in _iter_widget_states(data):
            if not key.startswith("webSearchResults"):
                continue
            raw_products: list[dict] = []
            _find_products(widget, raw_products)
            for raw in raw_products:
                product = self.parse_product(raw)
                if product is None or product.ext_id in seen:
                    continue
                seen.add(product.ext_id)
                products.append(product)
                if len(products) >= limit:
                    return products
        return products

    @staticmethod
    def parse_product(raw: dict) -> Product | None:
        """Сырой товар Ozon -> Product."""
        pid = raw.get("id") or raw.get("ext_id")
        if pid is None:
            return None
        title = raw.get("title") or raw.get("name") or "—"
        price_block = raw.get("price") or {}
        price = _to_rubles(price_block.get("price") or price_block.get("value"))
        old_price = _to_rubles(
            price_block.get("oldPrice")
            or price_block.get("old_price")
            or raw.get("old_price")
            or raw.get("oldPrice")
        )
        stock = _to_rubles(raw.get("stockCount"))
        if stock is None:
            stocks = raw.get("stocks")
            stock = _to_rubles(stocks.get("total")) if isinstance(stocks, dict) else None
        return Product(
            marketplace="ozon",
            ext_id=str(pid),
            title=str(title),
            price=price if price is not None else 0,
            old_price=old_price,
            url=f"https://www.ozon.ru/product/{pid}/",
            stock=stock,
            rating=None,
        )


class MockOzonAdapter:
    """Демо-режим: детерминированная выдуманная выдача по запросу."""

    name = "ozon"

    async def search(self, query: str, limit: int = 5) -> list[Product]:
        # zlib.crc32 вместо hash(): хэш строк рандомизируется между процессами
        seed = zlib.crc32(query.lower().encode("utf-8")) % 100
        base = 4700 + (seed * 29) % 3000
        return [
            Product(
                marketplace="ozon",
                ext_id=f"oz-{seed}-{i}",
                title=f"{query.title()} — вариант {i + 1} (Ozon, mock)",
                price=base + i * 200,
                old_price=base + i * 200 + 1200,
                url=f"https://www.ozon.ru/product/{seed}{i}/",
                stock=(seed + i * 5) % 25,
                rating=round(3.8 + (seed % 12) / 10, 1),
            )
            for i in range(limit)
        ]

    async def aclose(self) -> None:
        return None
