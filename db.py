"""Локальная SQLite-БД через aiosqlite: watch-запросы и история лучших цен.

Продвинутый уровень:
  - индексы на колонки, по которым идёт поиск (user_id, watch_id);
  - last_best_price/last_alert_at в watch — кулдаун уведомлений;
  - cleanup_history() — плановая очистка истории старше N дней;
  - stats() — сводка по базе для команды /stats.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import aiosqlite


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    async def init(self) -> None:
        """Создаёт таблицы и индексы при первом запуске."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS watches (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id          INTEGER,
                    query            TEXT,
                    threshold        INTEGER,      -- уведомить, если лучшая цена <= N
                    last_best_price  INTEGER,      -- лучшая цена, о которой уведомили
                    last_alert_at    TEXT,
                    created_at       TEXT
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS price_history (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    watch_id          INTEGER,
                    best_price        INTEGER,
                    best_marketplace  TEXT,
                    checked_at        TEXT
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_watches_user ON watches (user_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_watch ON price_history (watch_id)"
            )
            await db.commit()

    # ----------------------------------------------------------- watch

    async def add_watch(self, user_id: int, query: str, threshold: int | None) -> int:
        """Создаёт watch-подписку на запрос, возвращает её ID."""
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO watches (user_id, query, threshold, created_at) "
                "VALUES (?, ?, ?, ?)",
                (user_id, query, threshold, _now()),
            )
            await db.commit()
            return cur.lastrowid

    async def list_watches(self, user_id: int) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM watches WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            )
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def get_watch(self, watch_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM watches WHERE id = ?", (watch_id,))
            row = await cur.fetchone()
        return dict(row) if row else None

    async def delete_watch(self, user_id: int, watch_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "DELETE FROM watches WHERE id = ? AND user_id = ?",
                (watch_id, user_id),
            )
            await db.commit()
            return cur.rowcount > 0

    async def set_threshold(self, watch_id: int, threshold: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE watches SET threshold = ? WHERE id = ?",
                (threshold, watch_id),
            )
            await db.commit()

    async def all_watches(self) -> list[dict]:
        """Все watch-подписки всех пользователей (для планировщика)."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM watches ORDER BY id"
            )
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def update_last_notified(self, watch_id: int, best_price: int) -> None:
        """После уведомления запоминает лучшую цену и время."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE watches SET last_best_price = ?, last_alert_at = ? WHERE id = ?",
                (best_price, _now(), watch_id),
            )
            await db.commit()

    # ----------------------------------------------------------- история

    async def save_check(self, watch_id: int, best_price: int, marketplace: str) -> None:
        """Пишет результат проверки watch-запроса в историю."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO price_history (watch_id, best_price, best_marketplace, checked_at) "
                "VALUES (?, ?, ?, ?)",
                (watch_id, best_price, marketplace, _now()),
            )
            await db.commit()

    async def history(self, watch_id: int, limit: int = 15) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM price_history WHERE watch_id = ? ORDER BY id DESC LIMIT ?",
                (watch_id, limit),
            )
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def cleanup_history(self, keep_days: int) -> int:
        """Удаляет историю старше keep_days дней, возвращает число строк."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat(
            timespec="seconds"
        )
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "DELETE FROM price_history WHERE checked_at < ?", (cutoff,)
            )
            await db.commit()
            return cur.rowcount

    async def stats(self) -> dict:
        """Сводка по базе: watch-подписки, история, пользователи."""
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT COUNT(*) FROM watches") as cur:
                watches = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM price_history") as cur:
                history = (await cur.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM watches"
            ) as cur:
                users = (await cur.fetchone())[0]
        return {"watches": watches, "history": history, "users": users}
