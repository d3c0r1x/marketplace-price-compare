"""Компаратор: поиск одного запроса по нескольким маркетплейсам и сравнение.

merge_results() — чистая функция (легко тестируется): склеивает выдачи,
дедуплицирует по (marketplace, ext_id), сортирует по цене и помечает самый
дешёвый вариант. compare() — асинхронная обёртка: запускает адаптеры
параллельно (asyncio.gather), затем вызывает merge_results().
"""
from __future__ import annotations

import asyncio
import logging

from models import Product

logger = logging.getLogger(__name__)


def merge_results(*lists_per_market: list[Product]) -> list[Product]:
    """Склеивает выдачи маркетплейсов в один список.

    - дедупликация по (marketplace, ext_id): первый встреченный экземпляр;
    - сортировка по возрастанию цены;
    - товары с нулевой/неизвестной ценой (price == 0) уходят в конец.
    """
    merged: dict[tuple[str, str], Product] = {}
    for products in lists_per_market:
        for product in products:
            key = (product.marketplace, product.ext_id)
            if key not in merged:
                merged[key] = product

    def sort_key(p: Product) -> tuple[int, int]:
        # цена 0 (неизвестна) — максимум, чтобы не попасть в «самый дешёвый»
        return (p.price if p.price > 0 else 10**9, p.marketplace)

    return sorted(merged.values(), key=sort_key)


def best_deal(products: list[Product]) -> Product | None:
    """Самый дешёвый вариант с известной ценой (None, если таких нет)."""
    priced = [p for p in products if p.price and p.price > 0]
    return min(priced, key=lambda p: p.price) if priced else None


async def compare(
    query: str,
    adapters: list,
    limit: int = 5,
) -> tuple[list[Product], Product | None]:
    """Ищет запрос во всех маркетплейсах параллельно.

    Возвращает (отсортированный список, самый дешёвый вариант).
    Сбой одного маркетплейса не роняет остальные (возвращает [] для него).
    """
    async def safe_search(adapter) -> list[Product]:
        try:
            return await adapter.search(query, limit=limit)
        except Exception as exc:
            logger.warning("Маркетплейс %s упал: %s", getattr(adapter, "name", "?"), exc)
            return []

    per_market = await asyncio.gather(*(safe_search(a) for a in adapters))
    merged = merge_results(*per_market)
    return merged, best_deal(merged)
