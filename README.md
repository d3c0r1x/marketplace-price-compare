# Marketplace Price Compare

> **Prototype / supporting project.** The broader version of this idea lives in [Smart Shopper](https://github.com/d3c0r1x/smart-shopper).

Telegram bot that searches Ozon, Wildberries and Yandex Market in parallel, normalises results and compares offers.

## What it demonstrates

- parallel API calls;
- normalisation of different marketplace schemas;
- deduplication and sorting;
- price-watch subscriptions;
- scheduled background checks;
- SQLite persistence and tests.

## Stack

Python · aiogram · asyncio · SQLite · APScheduler · pytest · GitHub Actions

This repository is intentionally small and focused. For the end-to-end product with AI search, review analysis, Vision and a web Mini App, see Smart Shopper.
