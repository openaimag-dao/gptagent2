# API Reference

Base URL (local): `http://localhost:8000`. Full interactive docs (OpenAPI /
Swagger, generated automatically by FastAPI) are always available at
`/docs` on a running instance.

All endpoints return JSON. None require authentication -- the API is meant
to sit behind the same trust boundary as the Telegram bot and dashboard
consumers; see the audit for API auth as a known v1.0 gap.

## System

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check. `{"status": "ok"}` |

## Market data (Phase 1)

| Method | Path | Description |
|---|---|---|
| GET | `/api/market` | Latest snapshot across every collected symbol |
| GET | `/api/market/{symbol}/history?days=N` | Recent price history for one symbol |
| GET | `/api/btc` | Dedicated Bitcoin quote |

## News (Phase 2)

| Method | Path | Description |
|---|---|---|
| GET | `/api/news?category=&limit=` | Recent classified news, optional category filter |

## Analysis (Phases 3-6)

| Method | Path | Description |
|---|---|---|
| GET | `/api/correlations` | Latest rolling correlations (7/14/30/90d) |
| GET | `/api/regime` | Latest detected market regime |
| GET | `/api/signals` | Latest Bull/Bear signal score + factor breakdown |
| GET | `/api/report` | Latest AI-generated report |
| POST | `/api/report/generate` | Generates a fresh report on demand (needs `OPENAI_API_KEY`) |

## Historical Intelligence Engine (Sprint 2)

| Method | Path | Description |
|---|---|---|
| GET | `/api/history/{symbol}?timeframe=1d\|4h\|1h&limit=N` | OHLCV + indicators, most recent `limit` candles (1-5000, default 100) |
| GET | `/api/events` | Curated historical market events |

`{symbol}` must be one of the symbols in `app/services/history/registry.py`
(`BTC`, `ETH`, `SOL`, `NASDAQ`, `SPX`, `DJI`, `RUT`, the Magnificent 7,
`DXY`, `GOLD`, `SILVER`, `FEDRATE`, `VIX`, `US10Y`, `US30Y`, `OIL`, `CPI`,
`M2`). Returns 404 if the symbol is unknown or has no synced data yet, 400
if the timeframe isn't supported for that symbol (FRED-backed macro symbols
are daily-only).

## Probability, Pattern & Knowledge Engines (Sprint 3)

| Method | Path | Description |
|---|---|---|
| GET | `/api/probability/{symbol}?timeframe=1d` | Empirical RSI-conditioned forward-return probability (computed fresh each call) |
| GET | `/api/patterns/{symbol}?timeframe=1d&limit=10` | Detected candlestick/crossover patterns, most recent first |
| GET | `/api/knowledge/{symbol}?timeframe=1d&k=5` | K nearest historical analog episodes + real outcomes |

All three return 404 with an explanatory message if there isn't enough
synced history yet to compute a result -- run `sync_history.py` first.

## Error shape

FastAPI's default `HTTPException` shape:

```json
{"detail": "No BTC data collected yet"}
```

`400` = bad request parameter (invalid timeframe). `404` = valid request,
no data yet. `503` = `/api/report/generate` only, when regime/signal
detection hasn't run at least once yet.
