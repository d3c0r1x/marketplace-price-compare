"""Логика «уведомлять или нет» для watch-подписок — чистая функция.

Сравнивает новую лучшую цену с предыдущей: уведомляем, если лучшая цена
упала (появился более дешёвый вариант) или достигла порога. Кулдаун — не
чаще одного раза в cooldown_hours по одному watch-запросу.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


def should_notify(
    best_price: int,
    last_best_price: Optional[int],
    last_alert_at: Optional[str],
    *,
    threshold: Optional[int] = None,
    cooldown_hours: float = 12.0,
    now: Optional[datetime] = None,
) -> tuple[bool, list[str]]:
    """Возвращает (нужно_ли_уведомлять, список_сообщений)."""
    messages: list[str] = []

    if last_best_price is not None and best_price < last_best_price:
        messages.append(
            f"📉 <b>Лучшая цена упала!</b> Было {last_best_price} ₽ → стало {best_price} ₽"
        )
    if threshold is not None and best_price <= threshold:
        messages.append(
            f"🎯 <b>Порог достигнут!</b> Лучшая цена {best_price} ₽ (порог: {threshold} ₽)"
        )

    if not messages:
        return False, []

    if last_alert_at:
        try:
            last_alert_dt = datetime.fromisoformat(last_alert_at)
            now_dt = now or datetime.now(last_alert_dt.tzinfo)
            if now_dt - last_alert_dt < timedelta(hours=cooldown_hours):
                return False, []  # кулдаун ещё не истёк
        except ValueError:
            pass  # битая дата — не мешаем уведомлению
    return True, messages
