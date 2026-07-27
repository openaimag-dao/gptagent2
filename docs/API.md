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

## AI Market Intelligence Brain (Sprint 9)

| Method | Path | Description |
|---|---|---|
| GET | `/api/brain` | Latest report -- alias of `/api/report`, same engine |
| POST | `/api/brain/generate` | Generate a fresh report on demand -- alias of `/api/report/generate` |
| GET | `/api/similar/{symbol}?timeframe=1d&k=25` | 25 most similar historical periods, 1/3/7/30d forward returns, reconstructed regime |
| POST | `/api/backtest` | Backtest a structured rule. Body: `{"target_symbol", "conditions": [{"symbol","field","operator","value"}], "timeframe", "horizon"}` |
| POST | `/api/knowledge/rules` | Create a user knowledge-base rule; auto-backtested on creation |
| GET | `/api/knowledge/rules` | List all rules |
| GET | `/api/knowledge/rules/{id}` | Get one rule + its latest backtest result |
| POST | `/api/knowledge/rules/{id}/backtest` | Re-run a rule's backtest |
| GET | `/api/etf?window_hours=72` | ETF news-sentiment flow proxy (`"proxy_only": true` -- not confirmed dollar flows) |
| GET | `/api/whales?symbol=BTC` | Derivatives-positioning snapshot (funding rate, open interest, liquidations, long/short ratio) -- falls back to CoinGecko's keyless `/derivatives` endpoint (funding rate + open interest only) if `COINGLASS_API_KEY` is unset or its call fails; `"available": false` only if that fallback also fails |
| GET | `/api/global-score` | Deterministic Risk-On/Off, Liquidity, Fear/Greed, Macro Pressure, Institutional Activity, Crypto/Stock Strength + one global 0-100 score |

`Condition.operator` is one of `gt`, `lt`, `gte`, `lte`. `Condition.field` is
any of: `close`, `return_pct`, `volatility`, `atr`, `rsi`, `macd`,
`macd_signal`, `macd_histogram`, `sma_20`, `sma_50`, `sma_200`,
`volume_change_pct`. A rule with conditions on multiple symbols is
evaluated with all symbols' history aligned by timestamp; missing data on
any referenced symbol/date means that date never fires (never guessed).

## Quant Hedge Fund Engine (V2)

| Method | Path | Description |
|---|---|---|
| GET | `/api/agents` | Raw output of all 5 specialist agents (Macro/Crypto/Equity/News/Sentiment) |
| GET | `/api/memory?category=&since=&limit=` | Read-only timeline over every stored history table; omit `category` for all |
| GET | `/api/scenarios` | 4 named forward scenarios, probabilities summing to 100 |
| GET | `/api/sentiment` | Real Fear & Greed Index + news sentiment; social/options honestly unavailable |
| GET | `/api/liquidity` | Focused liquidity/macro-pressure read from the Global Market Score |
| GET | `/api/conviction?symbol=BTC` | Confidence tier (Weak..Institutional) for the latest signal + probability |
| GET | `/api/portfolio?name=main` | Virtual portfolio valuation, exposure, drawdown, Health Score |
| POST | `/api/portfolio/positions?name=main` | Add a position. Body: `{"symbol", "quantity", "entry_price"}` (`entry_price` optional; `symbol` may be `CASH`) |
| DELETE | `/api/portfolio/positions/{id}` | Remove a position |

`/api/memory`'s `category` must be one of: `predictions`, `signals`,
`regime`, `correlations`, `patterns`, `similarity`, `knowledge_rules`,
`whale`, `etf`, `sentiment`, `global_score`, `news`, `macro_events`,
`alerts`. Smart Alert Engine detections are never exposed via a dedicated
endpoint -- read them through `/api/memory?category=alerts` or the
`/alerts`-less `/memory alerts` Telegram command; they're pushed to
Telegram directly when conviction-eligible.

The browser dashboard (`/dashboard/`, static files under
`app/static/dashboard/`) is a pure client of every endpoint above plus the
pre-existing ones -- it introduces no new backend behavior.

## Institutional Research Platform (V3)

| Method | Path | Description |
|---|---|---|
| GET | `/api/calendar?days_back=30&days_ahead=30` | Real economic calendar: FRED release dates (CPI/PPI/NFP/GDP) + curated FOMC meeting dates |
| GET | `/api/features/{symbol}?compute=false` | Latest (or freshly computed) derived feature snapshot: returns, momentum, RSI, MACD, ATR, volatility, drawdown, whale/ETF flow momentum |
| GET | `/api/research?symbol=&event=&horizon=1&timeframe=1d` | Forward-return statistics for a symbol after every occurrence of a curated event category |
| GET | `/api/research/notes/latest` | Latest AI Researcher daily note (deterministic discoveries + LLM write-up) |
| POST | `/api/research/notes/generate?window_hours=24` | Generate a fresh research note on demand |
| GET | `/api/events/impact?category=&symbol=&timeframe=1d` | Average 24h/7d/30d return after every occurrence of a curated event category |
| POST | `/api/strategy` | Run/walk-forward/Monte Carlo a condition-based strategy. Body: `{"target_symbol","conditions":[{"symbol","field","operator","value"}],"timeframe","horizon","stop_loss_pct","take_profit_pct","position_size_pct","mode":"run"\|"walk_forward"\|"monte_carlo","folds","n_simulations"}` |
| GET | `/api/hypothesis?limit=50` | Most recently tested AI hypotheses |
| POST | `/api/hypothesis/test` | Test one hypothesis. Body: `{"symbol","event_a","event_b"}` |
| POST | `/api/hypothesis/test-all` | Auto-generate and test the full default hypothesis set |
| GET | `/api/ranking?symbol=BTC&compute=false` | Signal factors ranked by real predictive edge (current vs. historical importance) |

`event`/`category` above accept the same curated categories as
`/api/events`: `cpi`, `ppi`, `nfp`, `gdp`, `fomc`, `ecb`, `boj`, `pboc`,
`halving`, `crash`, plus any other category present in
`HistoricalEvent`/`EconomicCalendarEvent`. `Condition.field`/`.operator`
for `/api/strategy` are the same as `/api/backtest` above.

No new environment variables were introduced for V3 -- `/api/calendar`
reuses the already-configured `FRED_API_KEY`, and the AI Researcher reuses
`ANTHROPIC_API_KEY`/`OPENAI_API_KEY` (degrades to a plain discovery list,
no note text, if neither is set).

## Error shape

FastAPI's default `HTTPException` shape:

```json
{"detail": "No BTC data collected yet"}
```

`400` = bad request parameter (invalid timeframe/operator). `404` = valid
request, no data yet. `503` = `/api/report(/brain)/generate` only, when
regime/signal detection hasn't run at least once yet or `OPENAI_API_KEY`
is unset.
