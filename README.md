# AI Market Intelligence Bot

A continuously-running AI market analyst covering Bitcoin, the broader crypto
market, US equities and the macro economy. This is not a price bot — the end
goal (later phases) is a Telegram assistant that explains **why** markets are
moving, not just that they moved.

This repository is being built phase by phase. So far it delivers
**Phase 1: live market data collection** and **Phase 2: the news engine**,
plus the foundational infrastructure every later phase depends on (config,
database, caching, scheduling).

## What's implemented so far

- **Config** (`app/config`) — a single `Settings` object (Pydantic
  `BaseSettings`) reading everything from environment variables / `.env`.
- **Database** (`app/database`) — async SQLAlchemy 2.0 models, session
  management, Alembic migrations, and a Redis client.
- **Market data providers** (`app/services/market`) — one class per data
  source, all implementing the same `MarketDataProvider` interface:
  - `CoinGeckoProvider` — BTC, ETH, SOL, total crypto market cap, BTC
    dominance.
  - `YFinanceStockProvider` — NASDAQ Composite, S&P 500, Dow Jones, Russell
    2000, and the Magnificent 7 (AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA).
  - `YFinanceMacroProvider` — US Dollar Index (DXY), Gold, Silver.
  - `FredMacroProvider` — Fed Funds Rate, VIX, US10Y, US30Y, WTI Oil, sourced
    from FRED (official, non-scraped, very reliable from server IPs).
- **Aggregator** (`app/services/market/aggregator.py`) — runs every provider
  concurrently; one provider failing (bad key, rate limit, network blip)
  never blocks the others.
- **Repository** (`app/services/market/repository.py`) — persists every
  collection run to Postgres and caches the latest snapshot in Redis.
- **Scheduler** (`app/scheduler`) — APScheduler job that triggers a
  collection run on a fixed interval, immediately on startup.
- **News providers** (`app/services/news`) — one `RSSNewsSource` class reused
  across 8 real feeds spanning all 6 required categories:
  - Federal Reserve — federalreserve.gov press releases
  - SEC — sec.gov press releases
  - ETF — ETF Database
  - Crypto — CoinDesk, Cointelegraph
  - Stocks — CNBC Top News, Investing.com Stock Market News
  - Macro — Investing.com Economy News
- **Sentiment classifier** (`app/services/news/classifier.py`) — a
  deterministic bullish/bearish/neutral lexicon classifier (Loughran-McDonald
  style phrase counting over title + summary). Zero-cost and needs no LLM
  key; Phase 6's AI Analysis will layer richer narrative reasoning on top of
  this same classified feed.
- **News aggregator/repository** (`app/services/news`) — same
  concurrent-and-fault-tolerant pattern as the market aggregator, with
  URL-based deduplication (`ON CONFLICT DO NOTHING`) so re-running collection
  never inserts the same story twice.
- **API** — `GET /health`, `GET /api/market`, `GET /api/market/{symbol}/history`,
  `GET /api/news` (optional `category`/`limit` query params). The full
  dashboard API is Phase 10.

Not yet built: correlation engine, regime detection, signal engine, AI
analysis/report generation, Telegram bot, automatic reports. These land in
later phases per the project roadmap.

## Architecture

```
app/
  config/         Pydantic Settings (env-var driven)
  database/        SQLAlchemy models, async session/engine, Redis client
  services/
    market/
      schemas.py    AssetQuote / MarketSnapshotResult (Pydantic)
      base.py        MarketDataProvider interface
      crypto/        CoinGecko provider
      stocks/        Yahoo Finance stock/index provider
      macro/         Yahoo Finance + FRED macro providers
      aggregator.py  Concurrent, fault-tolerant collection
      repository.py  Postgres persistence + Redis cache
    news/
      schemas.py     RawNewsItem / ClassifiedNewsItem (Pydantic)
      base.py         NewsSource interface
      rss_source.py   Generic RSS/Atom feed source
      sources.py      Registry of the 8 configured feeds
      classifier.py   Deterministic bullish/bearish/neutral lexicon
      aggregator.py   Concurrent, fault-tolerant collection
      repository.py   Postgres persistence with URL dedup
  scheduler/        APScheduler job wiring
  api/              FastAPI routers
  utils/            Logging, shared HTTP client + retry policy
  main.py           FastAPI app + lifespan-managed scheduler
alembic/            DB migrations
tests/              pytest suite (schemas, aggregator resilience)
```

Every provider returns the same normalized `AssetQuote` shape regardless of
source, so the aggregator, repository, API, and every future phase (signals,
correlations, AI analysis) work against one consistent schema.

### Data model

Two tables back everything:

- `snapshot_batches` — one row per collection run (`id`, `collected_at`).
- `asset_prices` — one row per quote in that run (`symbol`, `asset_class`,
  `price`, `change_24h`, `change_pct_24h`, `market_cap`, `volume_24h`,
  `source`, `extra` JSON, `recorded_at`), foreign-keyed to its batch.

This is intentionally denormalized into a single wide table (rather than
separate crypto/stock/macro tables) so that the correlation engine (Phase 3)
can query any symbol's time series with one simple `WHERE symbol = ...`
query, and so new asset types never require a schema change.

News gets its own table:

- `news_items` — one row per deduplicated story (`source`, `category`,
  `title`, `url` unique, `summary`, `sentiment`, `sentiment_score`,
  `published_at`, `fetched_at`).

### Resilience

Both aggregators (market data and news) run their sources concurrently via
`asyncio.gather(..., return_exceptions=True)`. A source that raises (missing
API key, rate limit, feed down, network error) is logged and skipped —
collection continues with whatever the other sources returned. The whole run
only fails if *every* source fails.

News deduplication happens at insert time: `NewsRepository.save_new_items()`
uses a single `INSERT ... ON CONFLICT (url) DO NOTHING`, so re-running
collection on overlapping feed content never creates duplicate rows and
never races across concurrent runs.

## Known operational limitation: Yahoo Finance

`YFinanceStockProvider` and the DXY/Gold/Silver part of `YFinanceMacroProvider`
use `yfinance`, which scrapes Yahoo Finance's undocumented endpoints — there is
no official free stock/commodity API without registration. **During this
build, this exact issue surfaced in testing**: Yahoo Finance persistently
returned HTTP 429 / empty responses to this sandbox's shared egress IP, even
after retries with backoff. This is a well-known, widely reported failure
mode for `yfinance` running from shared/datacenter/proxy IP ranges — it is
not specific to any bug in this code.

Consequences and mitigations already built in:

- Because of the aggregator's fault-tolerance, a fully-blocked Yahoo Finance
  never breaks the pipeline — crypto (CoinGecko) and five of the eight macro
  indicators (FRED) keep flowing regardless.
- `download_last_two_closes()` (`app/services/market/yfinance_utils.py`)
  retries the whole batch up to 3 times with backoff before giving up.
- If your deployment host's IP is also blocked, swap
  `YFinanceStockProvider`/`YFinanceMacroProvider` for a keyed vendor (Twelve
  Data, Finnhub, Alpha Vantage, Polygon.io) — write one class implementing
  `MarketDataProvider.fetch()` and pass it into
  `MarketDataAggregator(providers=[...])` in `app/scheduler/jobs.py`. No other
  code changes are required; every downstream consumer (DB, cache, API) only
  ever sees the normalized `AssetQuote` shape.

## Running locally

### Option A: Docker Compose (recommended)

```bash
cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN / OPENAI_API_KEY / COINGECKO_API_KEY / FRED_API_KEY
# (FRED_API_KEY is free: https://fred.stlouisfed.org/docs/api/api_key.html)
docker compose up --build
```

This starts Postgres, Redis, runs `alembic upgrade head`, then the API +
scheduler on `http://localhost:8000`.

### Option B: Local Python

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env   # point DATABASE_URL / REDIS_URL at your local services

alembic upgrade head
uvicorn app.main:app --reload
```

### Verifying it works

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/market
curl "http://localhost:8000/api/market/BTC/history?days=7"
curl http://localhost:8000/api/news
curl "http://localhost:8000/api/news?category=crypto&limit=10"
```

The scheduler runs both collectors immediately on startup, then market data
every `MARKET_DATA_INTERVAL_MINUTES` (default 5) and news every
`NEWS_COLLECTION_INTERVAL_MINUTES` (default 10).

### Tests

```bash
pytest
ruff check .
```

## Configuration

See `.env.example` for the full list. Nothing except infrastructure URLs
(`DATABASE_URL`, `REDIS_URL`) has a hardcoded secret default — every API key
is optional-per-provider: a provider missing its key raises a clear error
that the aggregator logs and skips, rather than fabricating data.

| Variable | Required for | Notes |
|---|---|---|
| `DATABASE_URL` | everything | defaults to the docker-compose Postgres |
| `REDIS_URL` | caching | defaults to the docker-compose Redis |
| `COINGECKO_API_KEY` | crypto data | optional; raises your rate limit |
| `FRED_API_KEY` | Fed rate, VIX, US10Y/30Y, Oil | free key required |
| `TELEGRAM_BOT_TOKEN` | Telegram bot (later phase) | not yet used |
| `OPENAI_API_KEY` | AI analysis (later phase) | not yet used |
| `MARKET_DATA_INTERVAL_MINUTES` | scheduler | default `5` |
| `NEWS_COLLECTION_INTERVAL_MINUTES` | scheduler | default `10` |

## Roadmap

Phase 1 Market Data ✅ → Phase 2 News Engine ✅ → Phase 3 Correlation Engine →
Phase 4 Market Regime Detection → Phase 5 Signal Engine → Phase 6 AI
Analysis → Phase 7 Telegram Commands → Phase 8 Automatic Reports → Phase 9
Database (already largely in place) → Phase 10 Dashboard API.
