"""Конфигурация бота через переменные окружения (stdlib os.getenv)."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BOT_TOKEN = os.getenv("MARKET_BOT_TOKEN", "")
DB_PATH = os.getenv("MARKET_DB_PATH", os.path.join(BASE_DIR, "comparator.db"))
# Демо-режим: не ходит в сеть, сравнивает выдуманные выборки
DEMO_MODE = os.getenv("MARKET_DEMO_MODE", "0") == "1"
# Периодичность повторного поиска по watch-запросам (минуты)
CHECK_INTERVAL_MINUTES = int(os.getenv("MARKET_CHECK_INTERVAL_MINUTES", "240"))
# Сколько результатов искать в каждом маркетплейсе
MAX_RESULTS_PER_MARKET = int(os.getenv("MARKET_MAX_RESULTS_PER_MARKET", "5"))
# API-ключ Yandex Market (бесплатный, выдаётся в кабинете разработчика Yandex)
YANDEX_API_KEY = os.getenv("MARKET_YANDEX_API_KEY", "")
# Регион поиска Yandex Market (213 = Москва; 225 = Россия)
YANDEX_REGION = int(os.getenv("MARKET_YANDEX_REGION", "213"))

# --- Транспорт HTTP (антибот-устойчивость, см. adapters/) ---
#   curl_cffi — имитация TLS/HTTP2-отпечатка Chrome (по умолчанию)
#   httpx     — стандартный асинхронный клиент
HTTP_CLIENT = os.getenv("MARKET_HTTP_CLIENT", "curl_cffi")
PROXY = os.getenv("MARKET_PROXY", "")
MAX_RETRIES = int(os.getenv("MARKET_MAX_RETRIES", "3"))

# --- Продвинутый уровень ---
# Кулдаун уведомлений по одному watch-запросу (часы)
ALERT_COOLDOWN_HOURS = float(os.getenv("MARKET_ALERT_COOLDOWN_HOURS", "12"))
# Хранить историю лучших цен N дней
HISTORY_KEEP_DAYS = int(os.getenv("MARKET_HISTORY_KEEP_DAYS", "30"))
# Минимальный интервал между сообщениями пользователя (секунды)
THROTTLE_MIN_INTERVAL = float(os.getenv("MARKET_THROTTLE_MIN_INTERVAL", "0.7"))
# ID администраторов для /cleanup (через запятую; пусто = доступно всем)
ADMIN_IDS = [int(x) for x in os.getenv("MARKET_ADMIN_IDS", "").split(",") if x.strip().isdigit()]
# TTL кэша поисковых выдач (секунды)
CACHE_TTL_SECONDS = float(os.getenv("MARKET_CACHE_TTL_SECONDS", "300"))
