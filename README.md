# Marketplace Price Compare

> **Небольшой прикладной проект, который оставляю как единственный представитель серии marketplace-прототипов.**
>
> Он показывает базовую инженерную задачу без перегруза AI: параллельно запросить несколько площадок, привести разные ответы к одной модели, сравнить предложения и сохранить наблюдение за ценой.
>
> Более крупное развитие идеи находится в [Smart Shopper](https://github.com/d3c0r1x/smart-shopper).

## Что делает

Telegram-бот одновременно ищет товар на:

- Ozon;
- Wildberries;
- Яндекс Маркете.

Результаты нормализуются к общей модели, сортируются, дедуплицируются и могут использоваться для price watch.

## Основной сценарий

```
user query
    ↓
parallel adapters
    ├─ Ozon
    ├─ Wildberries
    └─ Yandex Market
    ↓
normalisation
    ↓
deduplication
    ↓
comparison / sorting
    ↓
Telegram response
```

Отдельный scheduler периодически проверяет watch-подписки и отправляет уведомление о выгодном изменении цены.

## Структура репозитория

```
adapters/
  base.py        # common adapter interface
  ozon.py        # Ozon adapter
  wb.py          # Wildberries adapter
  yandex.py      # Yandex adapter

alerts.py        # price-watch logic
comparator.py    # comparison / sorting
models.py        # common data models
db.py            # SQLite
bot.py           # Telegram handlers
middlewares.py   # throttling / logging
utils.py         # cache / retry

tests/
  test_adapters.py
  test_comparator_db_alerts.py
  test_live_flow.py
```

## Быстрый запуск

### Requirements

- Python 3.11+;
- Telegram Bot Token.

### Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Windows:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
start.bat
```

Для первого запуска оставьте:

```
MARKET_DEMO_MODE=1
```

Так приложение не зависит от внешних API.

## Примеры

В Telegram:

```
/start
```

затем запрос товара обычным текстом через меню поиска.

Пример:

```
беспроводные наушники до 5000 ₽
```

Для настройки price watch используется механизм подписок из `alerts.py`.

## Demo mode

```
MARKET_DEMO_MODE=1
```

Demo mode нужен, чтобы:

- воспроизводить результат;
- не зависеть от антибот-защиты;
- показывать архитектуру без приватных ключей.

## Реальные источники

`.env.example` содержит:

```
MARKET_HTTP_CLIENT=curl_cffi
MARKET_PROXY=
MARKET_MAX_RETRIES=3
MARKET_YANDEX_API_KEY=
MARKET_YANDEX_REGION=213
```

Маркетплейсы могут ограничивать автоматические запросы. Для реального режима нужен рабочий сетевой маршрут и актуальные web/API endpoint'ы.

## Конфигурация

| Переменная | Назначение |
|---|---|
| `MARKET_DEMO_MODE` | demo / real |
| `MARKET_HTTP_CLIENT` | HTTP client |
| `MARKET_PROXY` | proxy |
| `MARKET_MAX_RETRIES` | retries |
| `MARKET_CHECK_INTERVAL_MINUTES` | price watch |
| `MARKET_MAX_RESULTS_PER_MARKET` | results per source |
| `MARKET_YANDEX_API_KEY` | Yandex API |
| `MARKET_YANDEX_REGION` | region |
| `MARKET_ALERT_COOLDOWN_HOURS` | alert cooldown |
| `MARKET_HISTORY_KEEP_DAYS` | price history |
| `MARKET_CACHE_TTL_SECONDS` | search cache |

## Тесты

```bash
pytest -q
```

Проверяются adapters, comparator, DB, alerts и общий flow.

## Почему именно этот проект оставлен

Он компактный и легко читается как самостоятельный engineering case:

- concurrency;
- adapters;
- common schema;
- comparison;
- persistent state;
- scheduled background work.

При этом более сложную версию той же продуктовой линии можно посмотреть в Smart Shopper.

## AI-assisted development

AI использовался как ускоритель реализации и тестовых идей. Я отвечал за декомпозицию, интеграции, debugging и проверку результата.

## Лицензия

MIT.
