"""Адаптеры маркетплейсов: единый интерфейс search(query) -> list[Product]."""
from adapters.ozon import MockOzonAdapter, OzonAdapter
from adapters.wb import MockWbAdapter, WbAdapter
from adapters.yandex import MockYandexAdapter, YandexAdapter

__all__ = [
    "OzonAdapter", "MockOzonAdapter",
    "WbAdapter", "MockWbAdapter",
    "YandexAdapter", "MockYandexAdapter",
]
