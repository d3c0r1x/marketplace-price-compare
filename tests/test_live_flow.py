"""Интеграционный тест полного сценария бота сравнения цен.

В отличие от unit-тестов, здесь апдейты Telegram прогоняются через НАСТОЯЩИЙ
Dispatcher: router, middleware, хендлеры и БД бота (тот же код, что и в bot.py).
Исходящие вызовы Bot API перехватываются CapturingSession — сеть не нужна,
тест детерминирован (демо-адаптеры на crc32 воспроизводимы между запусками).

Сценарий: /start → /search наушники → /watch наушники 3000 → /watches →
/history 1. Плюс проверка /unwatch и поиска с пустой выдачей.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import bot as botmod
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, Update, User
from db import Database
from middlewares import LoggingMiddleware, ThrottlingMiddleware
from utils import TTLCache

USER_ID = 777
USERNAME = "live_tester"
FAKE_TOKEN = "12345:test-only-no-network"


class CapturingSession(BaseSession):
    """Перехватывает исходящие вызовы Bot API и записывает их в self.calls."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict] = []

    async def make_request(
        self, bot: Bot, method: TelegramMethod, timeout: int | None = None
    ):
        data = method.model_dump(exclude_none=True)
        self.calls.append({"method": type(method).__name__, "data": data})
        return _fake_result(method, data)

    async def close(self) -> None:
        return None

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        yield b""


def _fake_result(method: TelegramMethod, data: dict):
    name = type(method).__name__
    if name == "SendMessage":
        return Message(
            message_id=1,
            date=datetime.now(),
            chat=Chat(id=USER_ID, type="private"),
            text=data.get("text", ""),
        )
    return True


def _user() -> User:
    return User(id=USER_ID, is_bot=False, first_name="Live", username=USERNAME)


def _chat() -> Chat:
    return Chat(id=USER_ID, type="private")


def _msg_update(text: str, message_id: int, update_id: int) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=message_id,
            date=datetime.now(),
            chat=_chat(),
            from_user=_user(),
            text=text,
        ),
    )


def _send_texts(session: CapturingSession) -> list[str]:
    return [c["data"].get("text", "") for c in session.calls if c["method"] == "SendMessage"]


# Роутер бота можно прикрепить только к ОДНОМУ Dispatcher'у (aiogram кидает
# RuntimeError при повторном include_router), поэтому Dispatcher создаётся один
# раз на весь тестовый модуль и переиспользуется во всех сценариях.
DP = Dispatcher()
DP.include_router(botmod.router)
# interval=0: в тесте апдейты идут без задержек, троттлинг не должен их дропать
DP.message.middleware(ThrottlingMiddleware(min_interval=0.0))
DP.update.middleware(LoggingMiddleware())


def _make_bot(session: CapturingSession) -> Bot:
    return Bot(
        token=FAKE_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )


def _reset_state(db_path: str, adapters: list | None = None) -> None:
    """Свежая БД, чистый кэш, демо-адаптеры (изоляция между тестами)."""
    from adapters import MockOzonAdapter, MockWbAdapter, MockYandexAdapter

    botmod.adapters = adapters if adapters is not None else [MockWbAdapter(), MockOzonAdapter(), MockYandexAdapter()]
    botmod.search_cache = TTLCache(ttl_seconds=300.0)
    botmod.db = Database(db_path)


# ---------------------------------------------------------------- сценарии

def test_search_watch_history_flow(tmp_path) -> None:
    """/start → /search → /watch → /watches → /history + проверка БД."""
    db_path = str(tmp_path / "cmp.db")

    async def run() -> None:
        _reset_state(db_path)
        await botmod.db.init()
        session = CapturingSession()
        bot = _make_bot(session)
        dp = DP

        upd = mid = 0

        # /start — приветствие со списком команд
        await dp.feed_update(bot, _msg_update("/start", mid := mid + 1, upd := upd + 1))
        assert any("Marketplace Price Comparison" in t for t in _send_texts(session))
        assert any("/search" in t for t in _send_texts(session))

        # /search наушники — «Ищу…» + выдача со всеми тремя маркетплейсами и 🏆
        session.calls.clear()
        await dp.feed_update(bot, _msg_update("/search наушники", mid := mid + 1, upd := upd + 1))
        texts = _send_texts(session)
        assert any("🔍 Ищу" in t and "наушники" in t for t in texts)
        result = next(t for t in texts if "Сравнение цен" in t)
        assert "🟣 WB" in result and "🟢 Ozon" in result and "🔵 Яндекс" in result
        assert "🏆" in result                      # самый дешёвый помечен
        expected = botmod.config.MAX_RESULTS_PER_MARKET
        assert result.count("wildberries.ru") == expected  # все результаты WB со ссылками
        assert "ozon.ru" in result and "market.yandex.ru" in result

        # /watch наушники 3000 — подписка с порогом
        session.calls.clear()
        await dp.feed_update(bot, _msg_update("/watch наушники 3000", mid := mid + 1, upd := upd + 1))
        watch_texts = _send_texts(session)
        assert any("Подписка #1" in t and "создана" in t for t in watch_texts)
        assert any("Текущая лучшая цена" in t for t in watch_texts)
        # порог в ответе: «...опустится до 3000 ₽ или ниже»
        assert any("Уведомлю, когда лучшая цена опустится до 3000 ₽" in t for t in watch_texts)

        # /watches — подписка в списке с порогом и лучшей ценой
        session.calls.clear()
        await dp.feed_update(bot, _msg_update("/watches", mid := mid + 1, upd := upd + 1))
        watches = _send_texts(session)
        assert any("Ваши подписки" in t for t in watches)
        assert any("#1" in t and "наушники" in t and "порог 3000 ₽" in t and "лучшая:" in t for t in watches)

        # /history 1 — одна запись истории лучшей цены
        session.calls.clear()
        await dp.feed_update(bot, _msg_update("/history 1", mid := mid + 1, upd := upd + 1))
        hist = _send_texts(session)
        assert any("История лучшей цены" in t and "#1" in t for t in hist)
        assert any("— <b>" in t and "₽</b>" in t for t in hist)  # строка вида «дата — 5000 ₽ (WB)»

        # БД: подписка создана, история записана, last_best_price установлен
        watch = await botmod.db.get_watch(1)
        assert watch is not None
        assert watch["user_id"] == USER_ID
        assert watch["query"] == "наушники"
        assert watch["threshold"] == 3000
        assert watch["last_best_price"] > 0
        assert len(await botmod.db.history(1)) == 1

        # повторный /search того же запроса — кэш работает (2 обращения в кэше)
        session.calls.clear()
        await dp.feed_update(bot, _msg_update("/search наушники", mid := mid + 1, upd := upd + 1))
        assert any("Сравнение цен" in t for t in _send_texts(session))

        await bot.session.close()

    asyncio.run(run())


def test_unwatch_and_no_results(tmp_path) -> None:
    """/unwatch удаляет подписку; пустая выдача даёт понятный ответ."""
    db_path = str(tmp_path / "cmp.db")

    async def run() -> None:
        _reset_state(db_path)
        await botmod.db.init()
        session = CapturingSession()
        bot = _make_bot(session)
        dp = DP

        upd = mid = 0
        await dp.feed_update(bot, _msg_update("/watch наушники", mid := mid + 1, upd := upd + 1))
        assert any("Подписка #1" in t for t in _send_texts(session))

        # /unwatch 1 — удаление
        session.calls.clear()
        await dp.feed_update(bot, _msg_update("/unwatch 1", mid := mid + 1, upd := upd + 1))
        assert any("Подписка #1 удалена" in t for t in _send_texts(session))
        assert await botmod.db.get_watch(1) is None

        # /unwatch 1 ещё раз — «не найдена»
        session.calls.clear()
        await dp.feed_update(bot, _msg_update("/unwatch 1", mid := mid + 1, upd := upd + 1))
        assert any("не найдена" in t for t in _send_texts(session))

        # /history 1 после удаления — «не найдена»
        session.calls.clear()
        await dp.feed_update(bot, _msg_update("/history 1", mid := mid + 1, upd := upd + 1))
        assert any("Подписка не найдена" in t for t in _send_texts(session))

        # поиск с пустой выдачей (адаптер-заглушка) — понятное сообщение
        class EmptyAdapter:
            name = "empty"

            async def search(self, query, limit=5):
                return []

            async def aclose(self):
                return None

        _reset_state(str(tmp_path / "cmp_empty.db"), adapters=[EmptyAdapter(), EmptyAdapter()])
        await botmod.db.init()
        session.calls.clear()
        await dp.feed_update(bot, _msg_update("/search чего-то-нет", mid := mid + 1, upd := upd + 1))
        texts = _send_texts(session)
        assert any("Ничего не нашлось" in t for t in texts)

        await bot.session.close()

    asyncio.run(run())


def test_watch_requires_query(tmp_path) -> None:
    """/watch без запроса отклоняется с подсказкой формата."""
    db_path = str(tmp_path / "cmp.db")

    async def run() -> None:
        _reset_state(db_path)
        await botmod.db.init()
        session = CapturingSession()
        bot = _make_bot(session)
        dp = DP

        upd = mid = 0
        await dp.feed_update(bot, _msg_update("/watch", mid := mid + 1, upd := upd + 1))
        texts = _send_texts(session)
        assert any("Формат: /watch ЗАПРОС" in t for t in texts)

        # /search без запроса тоже отклоняется
        session.calls.clear()
        await dp.feed_update(bot, _msg_update("/search", mid := mid + 1, upd := upd + 1))
        assert any("Формат: /search ЗАПРОС" in t for t in _send_texts(session))

        await bot.session.close()

    asyncio.run(run())
