"""Единая модель товара из любого маркетплейса (pydantic).

Адаптеры WB и Ozon приводят свои ответы к этой модели, чтобы компаратор
мог смешивать и сортировать выдачи без знания внутренностей API.
"""
from __future__ import annotations

from pydantic import BaseModel


class Product(BaseModel):
    """Товар в поисковой выдаче маркетплейса.

    marketplace — "wb" или "ozon"; ext_id — идентификатор внутри площадки;
    price — текущая цена в рублях (целое); old_price — цена до скидки;
    url — прямая ссылка на карточку товара; stock — остаток (None = неизвестен).
    """

    marketplace: str
    ext_id: str
    title: str
    price: int
    old_price: int | None = None
    url: str
    stock: int | None = None
    rating: float | None = None

    def discount_percent(self) -> int | None:
        """Скидка в процентах (0, если нет старой цены)."""
        if not self.old_price or self.old_price <= 0:
            return None
        return round((1 - self.price / self.old_price) * 100)
