"""Тесты P11: компаратор, БД watch-подписок, логика уведомлений.

Запуск: python -m pytest tests -q
"""
import asyncio
from datetime import datetime, timedelta, timezone

from adapters import MockOzonAdapter, MockWbAdapter
from alerts import should_notify
from comparator import best_deal, compare, merge_results
from db import Database
from models import Product


def _p(marketplace: str, ext_id: str, price: int, old_price: int | None = None) -> Product:
    return Product(
        marketplace=marketplace,
        ext_id=ext_id,
        title=f"{marketplace}-{ext_id}",
        price=price,
        old_price=old_price,
        url=f"https://example.com/{ext_id}",
    )


# ------------------------------------------------------------ comparator

def test_merge_results_sorted_and_deduped() -> None:
    wb = [_p("wb", "1", 5000), _p("wb", "2", 3000)]
    oz = [_p("ozon", "1", 4500), _p("ozon", "1", 4500)]  # дубль в одной выдаче
    merged = merge_results(wb, oz)
    # 3 уникальных: wb-1, wb-2, ozon-1; отсортированы по цене
    assert len(merged) == 3
    assert [p.price for p in merged] == [3000, 4500, 5000]
    # wb-1 и ozon-1 не схлопнулись: разные маркетплейсы
    ids = {(p.marketplace, p.ext_id) for p in merged}
    assert ("wb", "1") in ids and ("ozon", "1") in ids


def test_best_deal_ignores_zero_price() -> None:
    products = [_p("ozon", "x", 0), _p("wb", "y", 7000)]
    best = best_deal(products)
    assert best is not None and best.marketplace == "wb"
    assert best_deal([_p("ozon", "x", 0)]) is None


def test_compare_parallel_with_mocks() -> None:
    """compare() запускает оба адаптера и возвращает отсортированную выдачу."""
    async def run() -> None:
        merged, best = await compare(
            "смартфон", [MockWbAdapter(), MockOzonAdapter()], limit=3
        )
        assert len(merged) == 6
        assert best is not None
        assert best.price == min(p.price for p in merged)
        # отсортировано по цене
        assert [p.price for p in merged] == sorted(p.price for p in merged)

    asyncio.run(run())


def test_compare_broken_adapter_does_not_break_others() -> None:
    """Сбой одного маркетплейса не роняет второй (gather с обработкой)."""

    class Broken:
        name = "broken"

        async def search(self, query, limit=5):
            raise RuntimeError("boom")

        async def aclose(self):
            return None

    async def run() -> None:
        merged, best = await compare("тест", [Broken(), MockWbAdapter()], limit=3)
        assert len(merged) == 3  # только mock-WB
        assert all(p.marketplace == "wb" for p in merged)

    asyncio.run(run())


# ------------------------------------------------------------ db watch

def test_db_watch_roundtrip(tmp_path) -> None:
    async def run() -> None:
        db = Database(str(tmp_path / "cmp.db"))
        await db.init()
        wid = await db.add_watch(111, "наушники", 3000)
        assert wid > 0
        watches = await db.list_watches(111)
        assert len(watches) == 1 and watches[0]["query"] == "наушники"
        assert watches[0]["threshold"] == 3000

        await db.save_check(wid, 2500, "ozon")
        await db.update_last_notified(wid, 2500)
        watch = await db.get_watch(wid)
        assert watch["last_best_price"] == 2500

        assert len(await db.history(wid)) == 1
        assert await db.delete_watch(111, wid) is True
        assert await db.list_watches(111) == []
        s = await db.stats()
        assert s["watches"] == 0 and s["history"] == 1

    asyncio.run(run())


def test_db_watch_ownership(tmp_path) -> None:
    """Чужой пользователь не может удалить чужую подписку."""
    async def run() -> None:
        db = Database(str(tmp_path / "cmp.db"))
        await db.init()
        wid = await db.add_watch(111, "телефон", None)
        assert await db.delete_watch(222, wid) is False
        assert await db.delete_watch(111, wid) is True

    asyncio.run(run())


def test_cleanup_history(tmp_path) -> None:
    async def run() -> None:
        import aiosqlite
        db = Database(str(tmp_path / "cmp.db"))
        await db.init()
        wid = await db.add_watch(1, "x", None)
        async with aiosqlite.connect(db.path) as conn:
            old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat(timespec="seconds")
            await conn.execute(
                "INSERT INTO price_history (watch_id, best_price, best_marketplace, checked_at) "
                "VALUES (?, 100, 'wb', ?)", (wid, old),
            )
            await conn.commit()
        await db.save_check(wid, 90, "ozon")
        deleted = await db.cleanup_history(keep_days=30)
        assert deleted == 1
        assert len(await db.history(wid)) == 1

    asyncio.run(run())


# --------------------------------------------------------------- alerts

def test_alert_on_best_price_drop() -> None:
    now = datetime.now(timezone.utc)
    notify, msgs = should_notify(2500, 3000, None, now=now)
    assert notify and len(msgs) == 1 and "упала" in msgs[0]


def test_alert_threshold_and_cooldown() -> None:
    now = datetime.now(timezone.utc)
    notify, msgs = should_notify(2900, 3000, None, threshold=3000, now=now)
    assert notify and any("Порог достигнут" in m for m in msgs)
    # кулдаун
    alert_1h_ago = (now - timedelta(hours=1)).isoformat()
    notify, _ = should_notify(2500, 3000, alert_1h_ago, now=now, cooldown_hours=12)
    assert not notify
    # кулдаун истёк
    alert_2d_ago = (now - timedelta(days=2)).isoformat()
    notify, _ = should_notify(2500, 3000, alert_2d_ago, now=now, cooldown_hours=12)
    assert notify


def test_alert_no_change_silent() -> None:
    now = datetime.now(timezone.utc)
    notify, msgs = should_notify(3000, 3000, None, now=now)
    assert not notify and msgs == []
