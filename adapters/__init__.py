"""Адаптеры маркетплейсов: единый интерфейс search(query) -> list[Product]."""
from adapters.ozon import MockOzonAdapter, OzonAdapter
from adapters.wb import MockWbAdapter, WbAdapter

__all__ = ["OzonAdapter", "MockOzonAdapter", "WbAdapter", "MockWbAdapter"]
