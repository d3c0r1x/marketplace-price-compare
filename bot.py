"""Telegram-бот "Marketplace Price Comparison".

Стек: aiogram v3, httpx, curl_cffi (имитация Chrome), aiosqlite, apscheduler,
pydantic (модель товара).

Функции:
  - /search ЗАПРОС — сравнить цены на WB и Ozon, показать отсортированную
    выдачу с пометкой самого дешёвого варианта;
  - /watch ЗАПРОС [ЦЕНА] — подписаться на запрос: бот периодически ищет
    заново и уведомляет, если лучшая цена упала или достигла порога;
  - /watches — список подписок; /unwatch ID — удалить подписку;
  - /history ID — история лучших цен по подписке;
  - /diag — диагностика доступа к API; /stats — сводка по базе;
  - /cleanup ДНИ — очистка истории старше N дней (админ).

Запуск:  python bot.py   (предварительно задайте MARKET_BOT_TOKEN)
"""
from __future__ import annotations

import asyncio
import html as _html
import logging
import os

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from adapters import MockOzonAdapter, MockWbAdapter, OzonAdapter, WbAdapter
from alerts import should_notify
from comparator import best_deal, compare
from db import Database
from middlewares import LoggingMiddleware, ThrottlingMiddleware
from models import Product
from utils import TTLCache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(config.BASE_DIR, "bot.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

router = Router()
db = Database(config.DB_PATH)
adapters: list = []
search_cache = TTLCache(ttl_seconds=config.CACHE_TTL_SECONDS)


def _fmt_product(p: Product, cheapest: bool = False) -> str:
    """Строка товара для выдачи."""
    price = f"<b>{p.price} ₽</b>" if p.price and p.price > 0 else "цена неизвестна"
    old = f" <s>{p.old_price} ₽</s>" if p.old_price else ""
    market = "🟣 WB" if p.marketplace == "wb" else "🟢 Ozon"
    badge = " 🏆" if cheapest else ""
    stock = f", остаток {p.stock}" if p.stock not in (None, 0) else ""
    return (
        f"{market}{badge} — <a href=\"{p.url}\">{_html.escape(p.title[:60], quote=False)}</a>\n"
        f"   {price}{old}{stock}"
    )


def _make_adapters() -> list:
    if config.DEMO_MODE:
        logger.info("Адаптеры: демо-режим (выдуманные данные)")
        return [MockWbAdapter(), MockOzonAdapter()]
    return [WbAdapter(), OzonAdapter()]


# ---------------------------------------------------------------- команды

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я бот <b>Marketplace Price Comparison</b>.\\n\\n"
        "Сравниваю цены на одни и те же товары на <b>Wildberries</b> и <b>Ozon</b>.\\n\\n"
        "Команды:\\n"
        "• /search <b>ЗАПРОС</b> — сравнить цены прямо сейчас\\n"
        "• /watch <b>ЗАПРОС [ЦЕНА]</b> — следить за запросом, уведомить при падении цены\\n"
        "• /watches — мои подписки\\n"
        "• /unwatch <b>ID</b> — удалить подписку\\n"
        "• /history <b>ID</b> — история лучших цен по подписке\\n"
        "• /diag — диагностика доступа к API\\n"
        "• /stats — сводка по базе\\n"
        "• /cleanup <b>ДНИ</b> — очистить историю (админ)\\n\\n"
        "Пример: /search смартфон 5000 маха"
    )


@router.message(Command("search"))
async def cmd_search(message: Message) -> None:
    query = (message.text or "").replace("/search", "", 1).strip()
    if not query:
        await message.answer("Формат: /search ЗАПРОС (например, /search наушники беспроводные)")
        return
    await message.answer(f"🔍 Ищу «{query}» на Wildberries и Ozon…")
    products, best = await _compare_cached(query)
    if not products:
        await message.answer(
            "Ничего не нашлось. Возможные причины: маркетплейсы блокируют запросы "
            "с этого IP (см. /diag), либо по запросу действительно нет товаров."
        )
        return
    lines = [_fmt_product(p, cheapest=(best is not None and p.ext_id == best.ext_id and p.marketplace == best.marketplace))
             for p in products]
    await message.answer("📊 <b>Сравнение цен:</b>\\n" + "\\n".join(lines))


async def _compare_cached(query: str) -> tuple[list[Product], Product | None]:
    """Поиск с TTL-кэшем: повторный запрос в течение CACHE_TTL мгновенный."""
    return await search_cache.get_or_set(query.lower(), lambda: compare(query, adapters, limit=config.MAX_RESULTS_PER_MARKET))


@router.message(Command("watch"))
async def cmd_watch(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Формат: /watch ЗАПРОС [ЦЕНА] (например, /watch наушники 3000)")
        return
    query = " ".join(parts[1:])
    threshold = None
    last = parts[-1]
    if last.isdigit():
        threshold = int(last)
        query = " ".join(parts[1:-1])
    if not query:
        await message.answer("Укажите запрос: /watch ЗАПРОС [ЦЕНА]")
        return

    products, best = await _compare_cached(query)
    if not products:
        await message.answer("По запросу ничего не нашлось — подписка не создана.")
        return
    watch_id = await db.add_watch(message.from_user.id, query, threshold)
    best_price = best.price if best else 0
    await db.save_check(watch_id, best_price, best.marketplace if best else "—")
    await db.update_last_notified(watch_id, best_price)
    txt = (
        f"✅ Подписка #{watch_id} на запрос «{query}» создана.\\n"
        f"Текущая лучшая цена: <b>{best_price} ₽</b>"
        + (f" ({best.marketplace.upper()})" if best else "")
    )
    if threshold:
        txt += f"\\nУведомлю, когда лучшая цена опустится до {threshold} ₽ или ниже."
    else:
        txt += "\\nУведомлю при каждом падении лучшей цены."
    await message.answer(txt)


@router.message(Command("watches"))
async def cmd_watches(message: Message) -> None:
    rows = await db.list_watches(message.from_user.id)
    if not rows:
        await message.answer("У вас нет подписок. /watch ЗАПРОС")
        return
    lines = []
    for w in rows:
        text = f"• #{w['id']} — «{_html.escape(w['query'][:40], quote=False)}»"
        if w["threshold"]:
            text += f", порог {w['threshold']} ₽"
        if w["last_best_price"]:
            text += f", лучшая: <b>{w['last_best_price']} ₽</b>"
        lines.append(text)
    await message.answer("👁 <b>Ваши подписки:</b>\\n" + "\\n".join(lines))


@router.message(Command("unwatch"))
async def cmd_unwatch(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /unwatch ID")
        return
    removed = await db.delete_watch(message.from_user.id, int(parts[1]))
    if removed:
        await message.answer(f"Подписка #{parts[1]} удалена.")
    else:
        await message.answer(f"Подписка #{parts[1]} не найдена.")


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /history ID")
        return
    watch = await db.get_watch(int(parts[1]))
    if watch is None or watch["user_id"] != message.from_user.id:
        await message.answer("Подписка не найдена.")
        return
    rows = await db.history(watch["id"], limit=15)
    if not rows:
        await message.answer("История пуста.")
        return
    lines = [
        f"{r['checked_at'][:16]} — <b>{r['best_price']} ₽</b> ({r['best_marketplace'].upper()})"
        for r in rows
    ]
    await message.answer(
        f"📈 <b>История лучшей цены</b> по подписке #{watch['id']} «{_html.escape(watch['query'][:40], quote=False)}»:\\n"
        + "\\n".join(lines)
    )


@router.message(Command("diag"))
async def cmd_diag(message: Message) -> None:
    lines = []
    for adapter in adapters:
        try:
            products = await adapter.search("тест", limit=1)
            status = f"OK, {len(products)} результатов" if products else "HTTP-ответ есть, но товаров нет (возможен софт-блок)"
        except Exception as exc:
            status = f"ошибка: {type(exc).__name__}: {exc}"
        lines.append(f"• <b>{getattr(adapter, 'name', '?').upper()}</b>: {status}")
    await message.answer("🩺 <b>Диагностика маркетплейсов:</b>\\n" + "\\n".join(lines))


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    s = await db.stats()
    await message.answer(
        "📊 <b>Сводка по базе:</b>\\n"
        f"• Подписок: {s['watches']}\\n"
        f"• Записей истории: {s['history']}\\n"
        f"• Пользователей: {s['users']}"
    )


@router.message(Command("cleanup"))
async def cmd_cleanup(message: Message) -> None:
    if config.ADMIN_IDS and message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Команда доступна только администраторам.")
        return
    parts = (message.text or "").split()
    days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else config.HISTORY_KEEP_DAYS
    deleted = await db.cleanup_history(days)
    await message.answer(f"🧹 Удалено записей истории старше {days} дн.: {deleted}.")


# ----------------------------------------------------- фоновая проверка watch

async def scheduled_check() -> None:
    """Периодический повторный поиск по всем watch-подпискам и рассылка."""
    watches = await db.all_watches()
    if not watches:
        return
    logger.info("Плановая проверка: %d watch-подписок", len(watches))
    for watch in watches:
        try:
            products, best = await compare(
                watch["query"], adapters, limit=config.MAX_RESULTS_PER_MARKET
            )
        except Exception as exc:
            logger.warning("Ошибка проверки watch #%s: %s", watch["id"], exc)
            continue
        if best is None:
            continue
        await db.save_check(watch["id"], best.price, best.marketplace)
        notify, msgs = should_notify(
            best.price,
            watch["last_best_price"],
            watch["last_alert_at"],
            threshold=watch["threshold"],
            cooldown_hours=config.ALERT_COOLDOWN_HOURS,
        )
        if notify:
            await db.update_last_notified(watch["id"], best.price)
            try:
                await bot.send_message(
                    watch["user_id"],
                    f"<b>«{_html.escape(watch['query'][:60], quote=False)}»</b>\\n"
                    + "\\n".join(msgs)
                    + f"\\n\\n{_fmt_product(best, cheapest=True)}",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as exc:
                logger.warning("Не удалось отправить уведомление %s: %s", watch["user_id"], exc)


# ------------------------------------------------------------------- main

async def main() -> None:
    global adapters, bot
    if not config.BOT_TOKEN:
        logger.error("MARKET_BOT_TOKEN не задан (см. .env.example)")
        return
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.middleware(ThrottlingMiddleware(min_interval=config.THROTTLE_MIN_INTERVAL))
    dp.message.middleware(LoggingMiddleware())
    dp.include_router(router)

    await db.init()
    adapters = _make_adapters()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduled_check,
        "interval",
        minutes=config.CHECK_INTERVAL_MINUTES,
        id="market_check",
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info(
        "Бот запущен. Демо-режим: %s. Проверка watch каждые %d мин. Кулдаун: %.1f ч",
        config.DEMO_MODE, config.CHECK_INTERVAL_MINUTES, config.ALERT_COOLDOWN_HOURS,
    )

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        for adapter in adapters:
            await adapter.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
