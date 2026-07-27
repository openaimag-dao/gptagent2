# Deployment Guide

This project has been deployed and operated on Railway for real, and every
pitfall below was actually hit and fixed during that process -- not
speculative advice.

## Local (Docker Compose)

```bash
cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN / OPENAI_API_KEY / COINGECKO_API_KEY / FRED_API_KEY
docker compose up --build
```

Starts `postgres`, `redis`, `app` (FastAPI + scheduler, runs
`alembic upgrade head` on boot) and `bot` (Telegram long-polling, its own
process so scaling the API never spins up a second poller fighting over the
same token).

Historical backfill is a separate, opt-in profile so it never runs on a
normal `docker compose up`:

```bash
docker compose --profile history run --rm history-sync
```

## Railway (production)

### Services

One Railway **environment** (e.g. "production") should contain exactly
four services: `Postgres`, `Redis`, an app service (FastAPI) and a bot
service (Telegram). **Do not** create a second environment for the bot --
Railway environments are fully isolated (separate Postgres/Redis per
environment), so a bot service living in a different environment than the
app service will connect to an empty, unmigrated database and crash with
`UndefinedTableError`. This exact mistake was made and diagnosed during
this project's rollout; the fix was deleting the stray environments and
recreating the bot as a second **service** inside the same environment as
`app`.

### Variables

Point both the app and bot service at Postgres/Redis via Railway's variable
references, not manually reconstructed connection strings:

```
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
```

Railway's own `DATABASE_URL` uses the bare `postgresql://` scheme; this
project's `Settings.database_url` validator
(`app/config/settings.py`) automatically rewrites that to
`postgresql+asyncpg://`, so pointing `DATABASE_URL` straight at
`${{Postgres.DATABASE_URL}}` just works -- no manual reassembly from
`PGUSER`/`PGPASSWORD`/`PGHOST`/`PGPORT` needed (that manual-reconstruction
path is exactly what produced a real `ValueError: invalid literal for
int() with base 10: ''` in production from an empty interpolated port).

Avoid Railway's "Shared Variables" feature for this -- it broke a
previously-working `app` service during testing (reverted the resolved
`DATABASE_URL` to empty). Plain per-service variables referencing
`${{Postgres.DATABASE_URL}}` directly are more reliable.

Required variables per service:

| Variable | app | bot | Notes |
|---|---|---|---|
| `DATABASE_URL` | required | required | `${{Postgres.DATABASE_URL}}` |
| `REDIS_URL` | required | required | `${{Redis.REDIS_URL}}` |
| `TELEGRAM_BOT_TOKEN` | - | required | from @BotFather |
| `GEMINI_API_KEY` | required* | - | for `/api/report/generate` and scheduled reports (*not required if `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is set instead); preferred provider -- genuine ongoing free tier, free key: https://aistudio.google.com/apikey |
| `ANTHROPIC_API_KEY` | optional | - | second choice, tried when Gemini is unconfigured or fails, falls back to OpenAI on its own failure |
| `OPENAI_API_KEY` | optional | - | last-resort fallback, or the only provider if Gemini/Anthropic are both unconfigured |
| `COINGECKO_API_KEY` | optional | - | raises free-tier rate limit; may be required for `sync_history.py`'s historical endpoint (observed 401 without one) |
| `FRED_API_KEY` | required for macro data | - | free: https://fred.stlouisfed.org/docs/api/api_key.html |
| `TWELVEDATA_API_KEY` | optional | - | primary source for indices/Mag 7/DXY/Gold/Silver, free tier 800 req/day |
| `ALPHAVANTAGE_API_KEY` | optional | - | Mag 7 + news sentiment fallback, free tier 5 req/min |
| `COINGLASS_API_KEY` | optional | - | primary derivatives-positioning source, free tier -- unconfigured falls back to CoinGecko's keyless `/derivatives` endpoint automatically, no variable needed |
| `TELEGRAM_BROADCAST_CHAT_IDS` | - | optional | comma-separated chat IDs for scheduled report pushes |

### Start commands

- app: `sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT"`
- bot: `python -m app.telegram.main`

Use Railway's dynamic `$PORT`, never hardcode `8000` -- Railway assigns it.
**After editing a Custom Start Command or a variable, you must explicitly
click Deploy** (the pending-changes banner) -- editing alone does not
redeploy the service, which was mistaken for a bug during rollout.

### Running `sync_history.py` against production

The historical sync needs outbound network access and a real Postgres
connection; the simplest way to run it is directly on Railway itself,
which avoids any need to expose Postgres publicly:

1. Open the app (or bot) service -> **Console** tab (Railway's built-in
   one-off shell, running inside the same private network as the rest of
   the environment).
2. Run:
   ```
   alembic upgrade head
   python sync_history.py
   ```

This is preferable to connecting from a separate machine over Postgres's
public proxy URL, which requires exposing `DATABASE_PUBLIC_URL` and a raw
TCP connection that many restricted network environments (CI runners,
some sandboxes) block outright.

### Known log-volume pitfall

Any code path that logs a full traceback per-item in a loop (e.g. a
correlation computation across ~30 symbol pairs) can trip Railway's 500
logs/sec cap on a single upstream failure, silently dropping thousands of
log lines. `CorrelationEngine.compute_and_store()` intentionally does not
wrap its per-pair loop in `try/except` for this reason -- a real failure
propagates once to the job-level handler instead of once per pair.

### Known Telegram Markdown pitfall

Telegram's legacy `parse_mode="Markdown"` treats a lone `_` or `*` in
dynamic content (factor names, LLM-generated report prose) as an
unterminated formatting entity and rejects the whole message with
`TelegramBadRequest`. Every handler in `app/telegram/handlers.py` sends
through a `_answer()` helper that retries as plain text on that specific
error, so one malformed field degrades gracefully instead of crashing the
command.

## Operational limitations (real, not hypothetical)

- **Yahoo Finance** (`yfinance`) blocks/rate-limits shared or datacenter
  egress IPs, including both this project's sandbox and, at times,
  Railway's own IPs. The aggregator's fault tolerance means this never
  takes down the whole pipeline -- crypto (CoinGecko) and FRED-backed
  macro data keep flowing regardless.
- **CoinGecko's historical `/market_chart` endpoint** returned HTTP 401
  then 429 in this project's sandbox without an API key; expect the same
  from some hosts. A `COINGECKO_API_KEY` (free demo tier) or a
  less-restricted egress IP should resolve it.
