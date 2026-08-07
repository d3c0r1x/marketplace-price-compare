"""Тесты P11: парсинг выдач WB, Ozon и Yandex Market, mock-адаптеры, устойчивость.

Запуск: python -m pytest tests -q
"""
import asyncio
import json

from adapters.ozon import MockOzonAdapter, OzonAdapter
from adapters.wb import MockWbAdapter, WbAdapter
from adapters.yandex import MockYandexAdapter, YandexAdapter


class FakeTransport:
    """Транспорт-заглушка: отдаёт заранее заданные ответы по порядку."""

    def __init__(self, responses: list[tuple[int, str]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict | None]] = []

    async def get(self, url: str, *, params=None, headers=None) -> tuple[int, str]:
        self.calls.append((url, params, headers))
        if not self.responses:
            raise RuntimeError("FakeTransport: пустой список ответов")
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[idx]

    async def aclose(self) -> None:
        return None


# --------------------------------------------------------------- WB

def test_wb_parse_product_kopecks() -> None:
    """Цены WB приходят в копейках — parse_product делит на 100."""
    p = WbAdapter.parse_product(
        {"id": 17457977, "name": "Наушники", "priceU": 59900, "salePriceU": 39900, "qty": 7}
    )
    assert p is not None
    assert p.marketplace == "wb"
    assert p.price == 399 and p.old_price == 599
    assert p.stock == 7
    assert "wildberries.ru" in p.url
    assert p.discount_percent() == 33


def test_wb_parse_product_missing_id_none() -> None:
    assert WbAdapter.parse_product({"name": "no id"}) is None


def test_wb_search_via_fake_transport() -> None:
    payload = json.dumps({
        "data": {
            "products": [
                {"id": 1, "name": "Товар A", "priceU": 10000, "salePriceU": 8000},
                {"id": 2, "name": "Товар B", "priceU": 20000, "salePriceU": 15000},
            ]
        }
    })
    transport = FakeTransport([(200, payload)])
    adapter = WbAdapter(transport=transport, max_retries=2)
    products = asyncio.run(adapter.search("наушники", limit=5))
    assert len(products) == 2
    assert products[0].price == 80
    assert "query" in transport.calls[0][1]  # параметр поиска передаётся


def test_wb_search_blocked_returns_empty() -> None:
    """HTTP 429/403/пустой софт-блок -> пустой список, без исключений."""
    for response in [(429, "rate limit"), (403, "forbidden"), (200, json.dumps({"data": {"products": []}}))]:
        transport = FakeTransport([response])
        adapter = WbAdapter(transport=transport, max_retries=2)
        assert asyncio.run(adapter.search("тест", limit=5)) == []


# --------------------------------------------------------------- Ozon

def _ozon_search_response(raw_products: list[dict]) -> str:
    items = [{"action": {"content": {"product": p}}} for p in raw_products]
    return json.dumps({"widgetStates": {"webSearchResults777": json.dumps({"items": items})}})


def test_ozon_parse_product() -> None:
    p = OzonAdapter.parse_product(
        {
            "id": 1500516648,
            "title": "Наушники",
            "price": {"price": "3990.00", "oldPrice": "5990.00"},
            "stocks": {"total": 4},
        }
    )
    assert p is not None
    assert p.marketplace == "ozon"
    assert p.price == 3990 and p.old_price == 5990
    assert p.stock == 4
    assert "ozon.ru" in p.url


def test_ozon_search_via_fake_transport() -> None:
    payload = _ozon_search_response([
        {"id": 100, "title": "Товар O1", "price": {"price": "5000.00"}},
        {"id": 101, "title": "Товар O2", "price": {"price": "7000.00"}},
    ])
    transport = FakeTransport([(200, payload)])
    adapter = OzonAdapter(transport=transport, max_retries=2)
    products = asyncio.run(adapter.search("наушники", limit=5))
    assert len(products) == 2
    assert products[0].price == 5000
    # url параметр поиска корректный
    params = transport.calls[0][1]
    assert params["url"].startswith("/search/?")


def test_ozon_search_region_block_returns_empty() -> None:
    """HTTP 307 (антибот) -> пустой список, без исключений."""
    transport = FakeTransport([(307, "redirect")])
    adapter = OzonAdapter(transport=transport, max_retries=3)
    assert asyncio.run(adapter.search("тест", limit=5)) == []
    assert len(transport.calls) == 1  # 307 не ретраим


def test_ozon_dedup_same_product() -> None:
    """Один и тот же товар в нескольких виджетах попадает один раз."""
    payload = json.dumps({
        "widgetStates": {
            "webSearchResults1": json.dumps({
                "items": [
                    {"action": {"content": {"product": {"id": 5, "title": "T", "price": {"price": "100.00"}}}}}
                ]
            }),
            "webSearchResults2": json.dumps({
                "items": [
                    {"action": {"content": {"product": {"id": 5, "title": "T", "price": {"price": "100.00"}}}}}
                ]
            }),
        }
    })
    transport = FakeTransport([(200, payload)])
    adapter = OzonAdapter(transport=transport, max_retries=2)
    products = asyncio.run(adapter.search("тест", limit=5))
    assert len(products) == 1



# --------------------------------------------------------------- Yandex

def _yandex_search_response(raw_products: list[dict]) -> str:
    return json.dumps({"items": raw_products})


def test_yandex_parse_product() -> None:
    """parse_product: цены из рублей с дробной частью, ссылка, остатков нет."""
    p = YandexAdapter.parse_product(
        {
            "id": 1735217196,
            "name": "Наушники",
            "prices": {"value": 5499.0, "oldValue": 6999.0},
            "rating": 4.5,
        }
    )
    assert p is not None
    assert p.marketplace == "yandex"
    assert p.price == 5499 and p.old_price == 6999
    assert p.stock is None
    assert "market.yandex.ru" in p.url


def test_yandex_parse_missing_id_none() -> None:
    assert YandexAdapter.parse_product({"name": "no id"}) is None


def test_yandex_search_via_fake_transport() -> None:
    """Ключ уходит в Authorization; query и regionId передаются в параметрах."""
    payload = _yandex_search_response([
        {"id": 10, "name": "Товар Y1", "prices": {"value": 5499.0}},
        {"id": 11, "name": "Товар Y2", "prices": {"value": 6999.0}},
    ])
    transport = FakeTransport([(200, payload)])
    adapter = YandexAdapter(api_key="secret", transport=transport, max_retries=2)
    products = asyncio.run(adapter.search("наушники", limit=5))
    assert len(products) == 2
    assert products[0].price == 5499
    url, params, headers = transport.calls[0]
    assert url == "https://api.content.market.yandex.ru/v2/models"
    assert params["query"] == "наушники" and params["regionId"] == 213
    # ключ реально уходит в Authorization (регрессия: раньше терялся)
    assert headers["Authorization"] == "secret"


def test_yandex_no_key_no_network() -> None:
    """Без ключа адаптер не ходит в сеть и возвращает пустую выдачу."""
    transport = FakeTransport([(200, "{}")])
    adapter = YandexAdapter(api_key="", transport=transport, max_retries=2)
    assert asyncio.run(adapter.search("тест", limit=5)) == []
    assert transport.calls == []


def test_yandex_bad_key_returns_empty() -> None:
    """HTTP 401 (недействительный ключ) -> пустая выдача, без исключений."""
    transport = FakeTransport([(401, "unauthorized")])
    adapter = YandexAdapter(api_key="wrong", transport=transport, max_retries=2)
    assert asyncio.run(adapter.search("тест", limit=5)) == []

# --------------------------------------------------------------- mock

def test_mock_adapters_deterministic() -> None:
    """Демо-режим: одинаковый запрос -> одинаковые цены, все три маркетплейса."""
    wb1 = asyncio.run(MockWbAdapter().search("смартфон"))
    wb2 = asyncio.run(MockWbAdapter().search("смартфон"))
    oz = asyncio.run(MockOzonAdapter().search("смартфон"))
    ya = asyncio.run(MockYandexAdapter().search("смартфон"))
    assert [p.price for p in wb1] == [p.price for p in wb2]
    assert len(wb1) == len(oz) == len(ya) == 5
    assert all(p.marketplace == "wb" for p in wb1)
    assert all(p.marketplace == "ozon" for p in oz)
    assert all(p.marketplace == "yandex" for p in ya)
