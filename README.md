# AI Market Intelligence Bot

A continuously-running AI market analyst covering Bitcoin, the broader crypto
market, US equities and the macro economy. This is not a price bot -- it
explains **why** markets are moving, not just that they moved.

All 10 phases of the project roadmap are implemented: live market data
collection, a news engine, a correlation engine, market regime detection, a
bull/bear signal engine, LLM-driven AI analysis, a Telegram bot, automatic
scheduled reports, full data persistence, and a dashboard API.

Sprint 2 adds a **Historical Intelligence Engine**: a resumable, 10-year
historical OHLCV + technical-indicator database (daily/4h/1h) across crypto,
US equities/indices and macro indicators, synced via `python
sync_history.py` -- see [Sprint 2: Historical Intelligence
Engine](#sprint-2-historical-intelligence-engine) below.

Sprint 3 adds three more deterministic engines on top of that historical
database -- a **Probability Engine** (empirical RSI-conditioned forward-return
odds), a **Pattern Recognition Engine** (candlestick + moving-average
crossover detection) and a **Knowledge Engine** (nearest-historical-analog
search that now grounds the AI report's historical comparison in real past
dates instead of LLM improvisation) -- see [Sprint 3: Probability, Pattern
Recognition & Knowledge
Engines](#sprint-3-probability-pattern-recognition--knowledge-engines) below.

Sprint 9 (the "AI Market Intelligence Brain") extends every engine above into
an institutional-grade platform: a Global Market Score, a rule Backtest
Engine, a user-submitted Knowledge Rules base with automatic backtesting, a
25-period Similar Market Engine, a Self-Learning accuracy tracker, and an
honestly-scoped ETF/Whale Intelligence layer -- see [Sprint 9: AI Market
Intelligence Brain](#sprint-9-ai-market-intelligence-brain) below, including
which two engines needed a paid data source this project doesn't have and
what they do instead of fabricating numbers.

V2 ("Quant Hedge Fund Engine") decomposes the AI Brain into five specialist
agents (Macro/Crypto/Equity/News/Sentiment) synthesized by a Reasoning Agent,
adds a Market Memory Engine over every table this project already persists, a
deterministic multi-Scenario Engine, a Conviction Engine, an Explanation
Engine, a Smart Alert Engine that pushes real deltas to Telegram, a virtual
Portfolio Engine, and a browser dashboard -- see [V2: Quant Hedge Fund
Engine](#v2-quant-hedge-fund-engine) below.

## Architecture

```
app/
  config/              Pydantic Settings (env-var driven)
  database/            SQLAlchemy models, async session/engine, Redis client
  services/
    market/
      schemas.py        AssetQuote / MarketSnapshotResult (Pydantic)
      base.py            MarketDataProvider interface
      crypto/            CoinGecko provider (BTC, ETH, SOL, TOTAL, BTC.D)
      stocks/            Yahoo Finance indices + Magnificent 7 provider (now the last-resort link in the chain below)
      macro/             Yahoo Finance (DXY/Gold/Silver, last resort) + FRED (VIX/US10Y/US30Y/Oil/FedRate)
      providers/         Twelve Data + Alpha Vantage clients, Redis cooldown cache
      multisource_stocks.py   Twelve Data -> Alpha Vantage (Mag 7 only) -> yfinance -> unavailable
      multisource_macro.py    Twelve Data -> yfinance -> unavailable (DXY/Gold/Silver)
      aggregator.py      Concurrent, fault-tolerant collection
      repository.py      Postgres persistence + Redis cache
    news/
      schemas.py         RawNewsItem / ClassifiedNewsItem (Pydantic)
      base.py             NewsSource interface
      rss_source.py        Generic RSS/Atom feed source
      sources.py           Registry of the 8 configured feeds
      classifier.py        Deterministic bullish/bearish/neutral lexicon
      aggregator.py        Concurrent, fault-tolerant collection
      repository.py        Postgres persistence with URL dedup
    analysis/
      correlation.py     Rolling Pearson correlation engine (7/14/30/90d)
      regime.py          Market regime detection (rule-based)
      schemas.py         AIAnalysisContent (LLM response schema)
      report.py          ReportGenerator -- ties everything together for the LLM
    signals/
      engine.py          Bull/Bear weighted signal scoring
    history/             Sprint 2 -- see below
    probability/
      engine.py           Empirical RSI-conditioned forward-return probability
    patterns/
      detectors.py         Pure candlestick + SMA-crossover pattern functions
      engine.py             Scans history, upserts detected patterns
    knowledge/
      analysis.py           Pure nearest-historical-analog search (z-score distance)
      engine.py              Orchestration + LLM grounding-text builder
      rules.py                Sprint 9: user rules CRUD + auto-backtest
    global_score/
      engine.py               Sprint 9: deterministic Global Market Score composite
    backtest/
      conditions.py            Sprint 9: safe structured rule DSL (no eval)
      metrics.py                Sprint 9: win rate / drawdown / profit factor / Sharpe
      engine.py                  Sprint 9: runs a rule over full stored history
    similar_market/
      engine.py                  Sprint 9: 25-period historical analog search + regime reconstruction
    learning/
      engine.py                   Sprint 9: prediction-vs-reality accuracy tracker
    etf/
      engine.py                    Sprint 9: ETF news-sentiment flow proxy (honest, not fabricated $ flows)
    whales/
      engine.py                    Sprint 9: on-chain data interface (honest "not configured" without a key)
    common/
      scoring.py                    V2: shared clamp/center_scaled/weighted_average helpers
      formatting.py                 V2: shared AssetPrice -> Markdown/dict formatting
    agents/
      macro_agent.py                 V2: Macro Agent (Fed/DXY/rates/VIX/Gold/Silver/Oil)
      crypto_agent.py                 V2: Crypto Agent (BTC/ETH/SOL/TOTAL/BTC.D + whale/ETF)
      equity_agent.py                 V2: Equity Agent (indices + Magnificent 7)
      news_agent.py                    V2: News Agent (category-weighted market-impact estimate)
      sentiment_agent.py                V2: Sentiment Agent (wraps SentimentEngine)
      orchestrator.py                    V2: runs all 5 agents concurrently for the Reasoning Agent
    sentiment/
      fear_greed.py                V2: real Crypto Fear & Greed Index provider (no key needed)
      engine.py                      V2: Sentiment Engine (Fear&Greed + news, honest re: social/options)
    memory/
      engine.py                    V2: Market Memory -- read-only timeline over every stored table
    scenarios/
      engine.py                    V2: deterministic multi-scenario probability generator
    conviction/
      engine.py                    V2: confidence bucketing (Weak..Institutional)
    explanation/
      engine.py                    V2: evidence-pack assembly (indicators/macro/history/news/risk)
    alerts/
      detectors.py                 V2: pure delta-detection functions (regime/correlation/DXY/...)
      engine.py                      V2: runs detectors, gates by conviction, logs + broadcasts
    portfolio/
      analytics.py                 V2: pure exposure/diversification/health-score math
      engine.py                      V2: virtual portfolio CRUD + drawdown (reuses backtest metrics)
  llm/
    client.py            OpenAI-compatible async client factory
  telegram/
    bot.py                aiogram Bot/Dispatcher wiring
    handlers.py            /start /help /market /btc /macro /stocks /crypto /news /signals
                            /correlations /report /history /events /probability /patterns
                            /knowledge /brain /similar /backtest /whales /etf /score
                            /agents /scenarios /sentiment /liquidity /conviction /memory /portfolio
    formatters.py          Pure functions: ORM rows -> Markdown text
    broadcast.py           broadcast_text() shared by scheduled reports + Smart Alert Engine
    main.py                Entrypoint for the bot's own process
  scheduler/            APScheduler job wiring (collectors, analysis, reports, V2 engines, alerts)
  api/                  FastAPI routers -- market, btc, news, correlations, regime,
                         signals, report, history, events, probability, patterns, knowledge,
                         brain, similar, backtest, etf, whales, global-score, agents, memory,
                         scenarios, sentiment, liquidity, conviction, portfolio
  static/dashboard/     Vanilla HTML/CSS/JS browser dashboard (served at /dashboard, no build step)
  utils/                Logging, shared HTTP client + retry policy
  main.py               FastAPI app + lifespan-managed scheduler + /dashboard static mount
alembic/                DB migrations (24 tables across 10 revisions)
tests/                  pytest suite -- 201 tests, all pure-function/logic paths
                        + DB-free FastAPI route-wiring smoke tests
```

Every market/news source implements one interface (`MarketDataProvider` /
`NewsSource`) and returns one normalized shape (`AssetQuote` / `RawNewsItem`),
so every downstream consumer -- aggregator, repository, API, Telegram bot,
LLM prompt builder -- works against the same schema regardless of where the
data came from.

### Data model

| Table | Written by | Purpose |
|---|---|---|
| `snapshot_batches` + `asset_prices` | Phase 1 | Every market data collection run |
| `news_items` | Phase 2 | Deduplicated, sentiment-classified news |
| `correlations` | Phase 3 | Rolling Pearson correlations per pair/window |
| `market_regime_snapshots` | Phase 4 | Detected regime + the inputs that drove it |
| `signal_snapshots` | Phase 5 | Bull/Bear score + factor breakdown |
| `reports` | Phase 6 | Full AI-generated report: raw data + LLM narrative |
| `market_history` / `crypto_history` / `stock_history` / `macro_history` | Sprint 2 | Daily/4h/1h OHLCV + indicators |
| `historical_events` | Sprint 2 | Curated real market milestones (halvings, crashes, ...) |
| `probability_snapshots` | Sprint 3 | Empirical RSI-conditioned forward-return probabilities |
| `pattern_signals` | Sprint 3 | Detected candlestick / crossover patterns |
| `global_market_scores` | Sprint 9 | Deterministic Risk-On/Off, Liquidity, Fear/Greed, ... composite |
| `knowledge_rules` | Sprint 9 | User-submitted rules/theories + their auto-backtest results |
| `similar_market_matches` | Sprint 9 | Every Similar Market Engine comparison, stored for audit |
| `sentiment_snapshots` | V2 | Fear & Greed + news sentiment + honest social/options unavailability |
| `scenario_snapshots` | V2 | Named, probability-weighted forward scenarios |
| `whale_snapshots` / `etf_flow_snapshots` | V2 | Persisted history of every Whale/ETF read (available or not) |
| `alert_logs` | V2 | Every Smart Alert detection, broadcast or not (conviction-gated) |
| `portfolios` / `portfolio_positions` | V2 | Virtual portfolios and their holdings |

`asset_prices` is intentionally one wide table (not separate crypto/stock/macro
tables) so the correlation engine can query any symbol's time series with a
single `WHERE symbol = ...`, and adding a new asset type never needs a schema
change.

### Resilience

Every aggregator (market data, news) runs its sources concurrently via
`asyncio.gather(..., return_exceptions=True)`. A source that raises (missing
API key, rate limit, feed down, network error) is logged and skipped --
collection continues with whatever the other sources returned, and the run
only fails if *every* source fails. Every analysis engine (correlation,
regime, signals, report generation) follows the same philosophy: missing
data produces an honest "not available" / lower confidence, never a
fabricated value.

## The ten phases

1. **Market data collection** -- CoinGecko (crypto), Twelve Data with Alpha
   Vantage and Yahoo Finance as fallbacks (stocks/indices, DXY/Gold/Silver),
   FRED (Fed Funds Rate, VIX, US10Y, US30Y, Oil).
2. **News engine** -- 8 real RSS feeds across Federal Reserve, SEC, ETF,
   crypto, stocks and macro categories, deduplicated by URL, classified
   bullish/bearish/neutral by a deterministic finance-lexicon scorer.
3. **Correlation engine** -- rolling 7d/14d/30d/90d Pearson correlations of
   daily returns for BTC vs NASDAQ/DXY/GOLD/VIX/US10Y/SPX, ETH vs BTC, SOL
   vs BTC.
4. **Market regime detection** -- deterministic rules produce one of Risk
   On, Risk Off, Neutral, Liquidity Expansion, Liquidity Contraction, Flight
   to Safety, with the raw inputs stored for auditability.
5. **Signal engine** -- the spec's weighted factor table (NASDAQ +2, DXY
   -3→+3 on direction, Gold -1, ETF inflow +5, Fed dovish +4, VIX -3,
   US10Y -2) produces a Bull Score, Bear Score and Confidence %.
6. **AI analysis** -- an OpenAI-compatible LLM synthesizes everything above
   into a narrative explaining *why* markets moved: what changed, who's
   driving it, institutional interpretation, macro explanation, historical
   comparison, risks, key events, and bullish/bearish/neutral probabilities.
7. **Telegram bot** -- `/start /help /market /btc /macro /stocks /crypto
   /news /signals /report` (aiogram, runs as its own process).
8. **Automatic reports** -- a report every 30 minutes plus five named
   session reports (Asia, Europe, Morning, US Open, Daily Summary) on cron
   schedules, broadcast to Telegram.
9. **Database** -- Postgres via async SQLAlchemy + Alembic; every phase's
   output is persisted (see table above).
10. **Dashboard API** -- `GET /api/market`, `/api/btc`, `/api/news`,
    `/api/signals`, `/api/report` (plus `/api/correlations`, `/api/regime`
    and `POST /api/report/generate` as bonuses).

## Sprint 2: Historical Intelligence Engine

A second, independent build on top of the ten phases above: a resumable,
deep historical database, not just raw candles. Every stored bar also
carries return %, rolling volatility, ATR, RSI, MACD (line/signal/histogram),
SMA 20/50/200 and volume change, computed once and persisted -- a row's
indicators are never recalculated once set (`indicators_computed`).

```
app/services/history/
  schemas.py            Timeframe (1d/4h/1h), Candle (Pydantic)
  base.py                HistoricalDataProvider interface
  providers/
    coingecko.py           BTC/ETH/SOL daily + hourly (resampled to 4h)
    yfinance_provider.py    Indices, Magnificent 7, DXY/Gold/Silver
    fred.py                  Fed Rate/VIX/US10Y/US30Y/Oil/CPI/M2 (daily only)
  indicators.py          Pure functions: returns, volatility, ATR, RSI, MACD, SMA, volume change
  registry.py            The full symbol -> (table, provider, timeframes) universe
  repository.py          Upsert (dedup via unique constraint), fill-once indicators
  sync.py                HistorySyncEngine -- resumable, fault-tolerant per symbol/timeframe
  validation.py          Pure gap/duplicate detection over stored timestamps
  repair.py              Deletes duplicates, re-fetches candles across detected gaps
  events.py              Curated seed of well-documented market events (halvings, crashes, ...)
sync_history.py          CLI entrypoint
```

### Data model

| Table | Symbols |
|---|---|
| `market_history` | NASDAQ, S&P 500, Dow Jones, Russell 2000 |
| `stock_history` | AAPL, MSFT, NVDA, TSLA, AMZN, META, GOOGL |
| `crypto_history` | BTC, ETH, SOL |
| `macro_history` | DXY, Gold, Silver, Oil, US10Y, US30Y, VIX, Fed Rate, CPI, M2 |
| `historical_events` | Curated milestone events (halvings, COVID crash, FTX, SVB, ETF approval, ...) |

All four OHLCV tables share the same columns (open/high/low/close/volume plus
every indicator above) and a `UNIQUE(symbol, timeframe, timestamp)`
constraint, which is what actually enforces "no duplicates" --
`upsert_candles()` uses `INSERT ... ON CONFLICT DO NOTHING` against it, so
re-running a sync over an already-covered range is always a safe no-op.

### Usage

```bash
python sync_history.py                  # sync everything, 10y lookback
python sync_history.py --years 5
python sync_history.py --symbol BTC --timeframe 1d
python sync_history.py --validate-only  # just check for gaps/duplicates
python sync_history.py --no-repair      # report gaps/duplicates without fixing them
python sync_history.py --seed-events    # load the curated historical-events seed
```

Each run is resumable: `HistorySyncEngine` only asks a provider for candles
after the latest timestamp already stored for that symbol/timeframe, so a
daily cron of `python sync_history.py` never re-fetches or re-computes what
it already has. After syncing, it validates every synced symbol/timeframe for
gaps (a real hole in the data) and duplicates (structurally prevented by the
unique constraint going forward, but checked as a safety net for
pre-existing/imported data) and repairs what it can -- deleting duplicate
rows and re-fetching candles across detected gaps.

Gap detection is tolerance-aware: crypto trades 24/7 so any hole past 1.5x
the timeframe's step is flagged, but equities/macro close on weekends and
holidays, so their tolerance is 4x the step -- a normal Friday-to-Monday gap
is not a false positive.

### Known limitations (documented, not fabricated)

Consistent with this project's rule of never fabricating data, a few real
source constraints are documented rather than worked around with guesses:

- **TOTAL market cap and BTC dominance have no historical backfill.**
  CoinGecko's free API only exposes these via the live `/global` snapshot,
  not a historical endpoint -- they're excluded from `crypto_history` rather
  than approximated.
- **CoinGecko's free tier caps `/coins/{id}/market_chart` at 365 days of
  history**, live-verified against production (both keyless and with a
  `COINGECKO_API_KEY` Demo key): requesting `days=max` 401s with "Public API
  users are limited to querying historical data within the past 365 days" --
  a CoinGecko-side policy change, not a bug in this client. `_DAILY_DAYS` is
  set to `365` accordingly, so BTC/ETH/SOL backfill here is bounded to the
  trailing year regardless of the engine's configured `--years` lookback; a
  paid CoinGecko plan is the only way to get the full historical depth other
  symbols have. Separately, CoinGecko's per-minute rate limit can still 429
  a burst of calls (retried with backoff) -- a `COINGECKO_API_KEY` raises
  that ceiling but doesn't change the 365-day cap.
- **4h candles are resampled, not native.** Neither CoinGecko's free tier nor
  yfinance offers a native 4-hour bar; `resample.py` aggregates 1h bars up to
  4h, so 4h history is bounded by whatever 1h history is available.
- **yfinance intraday history is capped at roughly 730 days** by Yahoo
  itself, regardless of the requested period -- daily history has no such
  cap. The same shared-IP blocking risk documented for the live phase below
  applies here too, and reproduced during development.
- **FRED-sourced macro series (Fed Rate, VIX, US10Y, US30Y, Oil, CPI, M2) are
  daily/monthly only** -- FRED has no intraday data, so the registry never
  requests 4h/1h for them.

### What was actually verified live

Beyond the pure-function unit tests, the full pipeline was run against real
Postgres in this sandbox: `python sync_history.py --symbol US10Y --timeframe
1d --years 1` fetched 249 real FRED observations, inserted all 249, and
computed indicators for all 249 rows. Re-running the identical command
immediately after fetched 1 candle, inserted 0 (deduplicated) and recomputed
0 indicators (`indicators_computed` already `True`) -- confirming
incremental-resume and never-recalculate behavior end to end, not just in
unit tests. Migration 0007 was also verified with a full
upgrade/downgrade/upgrade cycle.

## Sprint 3: Probability, Pattern Recognition & Knowledge Engines

Three more deterministic engines built directly on Sprint 2's stored history
-- no new external data sources, no ML black boxes, no LLM guessing. Every
number either comes from real synced history or is honestly reported as
unavailable.

### Probability Engine (`app/services/probability/`)

Empirical, RSI-conditioned forward-return probability: buckets a symbol's own
historical RSI readings around its current value and measures what fraction
of those past occurrences were followed by a positive / negative / flat
return over the next N periods. Requires at least 8 matching historical
episodes or it returns nothing rather than a low-confidence guess.

```
GET /api/probability/{symbol}?timeframe=1d
/probability BTC [timeframe]
```

### Pattern Recognition Engine (`app/services/patterns/`)

Deterministic rule-based detectors over OHLCV + the moving averages already
computed in Sprint 2: Doji, Hammer, Bullish/Bearish Engulfing (classic
candlestick definitions), and Golden Cross / Death Cross (SMA 50 crossing SMA
200). Scans a symbol's full stored history and upserts every match, so
`/api/patterns` and `/patterns` return a real historical catalog, not just
the latest candle.

```
GET /api/patterns/{symbol}?timeframe=1d&limit=10
/patterns BTC [timeframe]
```

### Knowledge Engine (`app/services/knowledge/`)

Nearest-historical-analog search: z-score normalizes a symbol's RSI and
volatility history, finds the K most similar past candles to today's reading,
and reports what actually happened next (forward return) plus any curated
`historical_events` nearby. This is what fixed a real gap in the AI report:
before Sprint 3, `historical_comparison` was pure LLM improvisation with zero
real data behind it. Now `ReportGenerator` calls the Knowledge Engine for BTC
before every report and feeds the LLM a "HISTORICAL ANALOGS" section of real
dates and real outcomes, with an explicit instruction to ground its answer in
that data (or say plainly that no analog was found).

```
GET /api/knowledge/{symbol}?timeframe=1d&k=5
/knowledge BTC [timeframe]
```

### Known limitations

- Both the Probability and Knowledge engines need real variance in the
  underlying RSI/volatility series to produce a meaningful result (a flat or
  too-short series returns nothing, not a fabricated number).
- FRED-sourced macro symbols store flat OHLC (open == high == low == close,
  since FRED gives one value per day -- see Sprint 2), so candlestick
  patterns other than the SMA crossovers structurally can't fire on them;
  this was confirmed during live testing (`/api/patterns/US10Y` correctly
  returns zero patterns over a real 249-row window with FRED's flat OHLC).
- A full FastAPI `TestClient` + test-database integration suite is still a
  known gap for the whole project, not just these three engines -- see the
  audit for details.

### What was actually verified live

All three engines were run against the real `US10Y` history synced during
Sprint 2 testing (249 real FRED daily candles): the Probability Engine found
12 matching historical episodes and computed a real 42% up / 58% down split;
the Pattern Engine scanned the full series without error; the Knowledge
Engine returned 5 real historical analog dates with real forward returns. All
four new API endpoints (`/api/history`, `/api/events`, `/api/probability`,
`/api/patterns`, `/api/knowledge`) were then hit directly over HTTP against a
live-started FastAPI app, including a 404 check for an unknown symbol.
Migration 0008 was verified with a full upgrade/downgrade/upgrade cycle.

## Sprint 9: AI Market Intelligence Brain

Ten engines were requested; every one is addressed below -- eight fully
built on real data, two (Whale and ETF Intelligence) honestly scoped down
because full real-time on-chain/derivatives and ETF-flow data both require
paid providers not configured in this project. Nothing here fabricates a
number it can't back with real, already-computed data.

### 1. AI Brain Engine

Not a new implementation -- `ReportGenerator` (Sprint 1-3) already *was* the
brain engine (WHY/WHO's-driving/institutional/macro synthesis grounded in
real data). Sprint 9 enriches its inputs (Global Market Score, ETF proxy,
Whale snapshot) and output schema (`liquidity_and_risk`, `scenarios`,
`actionable_insights` fields added to `AIAnalysisContent`), and exposes it
under `/api/brain` + `/brain` as an explicit alias -- same engine, matching
name.

### 2. Similar Market Engine

Extends Sprint 3's Knowledge Engine analog search (same z-score nearest-
neighbor logic, not reimplemented) to 25 matches by default, 4 forward
horizons (1/3/7/30 periods), and -- new -- historical market regime
reconstruction: `detect_regime()` (Phase 4, unchanged) is re-run against
`market_history`/`crypto_history`/`macro_history` rows for each matched
date, so a historical regime tag means exactly the same thing as a live
one. Every comparison is persisted to `similar_market_matches`.

```
GET /api/similar/{symbol}?timeframe=1d&k=25
/similar BTC [timeframe]
```

### 3. Probability Engine

Sprint 3's engine, relabeled Bullish/Bearish/Neutral (`label_probability()`)
and extended with `contributing_indicators()` (pulls the Signal Engine's own
factor breakdown -- which real factors are driving the read) and real
historical-accuracy tracking (see Self-Learning Engine below). `/probability`
and `/api/probability` are unchanged endpoints, richer underlying engine.

### 4. Knowledge Engine (user rules)

A second, distinctly-named concept living in the same package as Sprint 3's
analog search (`app/services/knowledge/rules.py`): users submit a Theory,
Rule, Macro Idea or Crypto Idea as a structured condition (see Backtest
Engine's DSL below), and it's automatically backtested on creation and
whenever `POST /api/knowledge/rules/{id}/backtest` is called again. Every
rule stores occurrences, win rate, average return, drawdown, profit factor,
Sharpe ratio and a **confidence score that scales down with few historical
occurrences** (`compute_confidence_pct()`) -- two wins out of two never
reads as "100% confident."

```
POST /api/knowledge/rules   {"title", "description", "category", "author",
                              "target_symbol", "conditions": [...], "horizon_periods"}
GET  /api/knowledge/rules
GET  /api/knowledge/rules/{id}
POST /api/knowledge/rules/{id}/backtest
```

### 5. Backtest Engine

A small, deliberately safe condition DSL (`app/services/backtest/conditions.py`)
-- `Condition(symbol, field, operator, value)`, AND-combined, evaluated
against already-computed history fields (rsi, sma_50, return_pct, ...). Not
a free-text parser and not `eval()` -- structured input only. Runs any rule
over a target symbol's full stored history and returns win rate, average
return, max drawdown (peak-to-trough on the compounded trade sequence),
profit factor and annualized Sharpe ratio -- every metric returns `None`
rather than a fabricated number when the sample can't support it (no
losing trades for profit factor, fewer than 2 trades for Sharpe, zero
matches at all).

```
POST /api/backtest   {"target_symbol", "conditions": [...], "timeframe", "horizon"}
/backtest SYMBOL SYMBOL:field:op:value [...] [horizon]   (e.g. /backtest BTC BTC:rsi:lt:30 1)
```

### 6. Whale Intelligence -- derivatives positioning via CoinGlass/CoinGecko

Exchange inflow/outflow, large-wallet tracking and stablecoin supply changes
require a genuine on-chain wallet tracker (Glassnode, CryptoQuant) that isn't
configured anywhere in this project, and there's no reliable free equivalent
-- `WhaleIntelligenceEngine` never claims those fields. Funding rate and open
interest *are* available for real from CoinGlass (`COINGLASS_API_KEY`, free
tier) with CoinGecko's keyless `/derivatives` endpoint (no key needed) as a
fallback when CoinGlass is unconfigured or its call fails; 24h liquidations
and long/short ratio are CoinGlass-only, since CoinGecko's free derivatives
endpoint doesn't offer either. `classification` (`long_heavy` / `short_heavy`
/ `balanced`) is derived from funding rate + long/short ratio -- it describes
current leveraged derivatives positioning, not on-chain accumulation or
distribution, since neither source can honestly support that stronger claim.
If CoinGlass is unconfigured and the CoinGecko fallback call also fails, the
engine reports `"available": false` with a clear reason and the exact
response shape a real read would fill in -- the same principle that keeps
`FredMacroProvider` from inventing a Fed Funds Rate when `FRED_API_KEY` is
unset.

```
GET /api/whales?symbol=BTC
/whales [symbol]
```

### 7. ETF Intelligence -- real proxy, not fabricated flows

Real ETF creation/redemption dollar flows need a paid source too (Farside
Investors, SoSoValue). Instead of inventing a flow number, this surfaces
the one real signal already being collected: aggregate sentiment of
ETF-category news (the same proxy the Signal Engine's `etf_inflow` factor
already relies on), explicitly labeled `"proxy_only": true` in every
response so it's never mistaken for confirmed flow data. Verified live:
33 real ETF-category news items, correctly classified.

```
GET /api/etf?window_hours=72
/etf
```

### 8. Self-Learning Engine

`ProbabilitySnapshot` now stores `reference_timestamp` (the exact candle a
prediction was made from, not just wall-clock time). `LearningEngine`
compares every past prediction whose `horizon_periods` have actually
elapsed in stored history against what really happened, and reports real,
measured accuracy -- a prediction only counts once enough time has passed
for its outcome to exist. This is the honestly-scoped version of "self
learning": real measurement and comparison, not an unverified claim of
automatic weight retraining.

```
GET /api/learning/{symbol}?timeframe=1d
/learning SYMBOL [timeframe]
```

### 9. Global Market Score

A deterministic composite (`app/services/global_score/engine.py`) --
every sub-score traces to an already-computed input, nothing new is
fetched: Risk-On/Off from the regime classification, Liquidity from the
Fed Funds Rate direction, Fear/Greed from VIX, Macro Pressure from
DXY/US10Y, Institutional Activity from the Signal Engine's `etf_inflow`
factor, Crypto/Stock Strength from live price changes. One weighted
0-100 global score ties them together.

```
GET /api/global-score
/score
```

### 10. AI Daily Report

The existing `/report` (now also `/brain`) already covers most of the
requested structure (market/macro/crypto/stock summaries, correlations,
news, AI conclusion, probability, risks). Sprint 9 adds the remaining
sections: `liquidity_and_risk`, `scenarios` and `actionable_insights` to
`AIAnalysisContent`, plus a real (never LLM-generated) `institutional_summary`
JSON field on every `Report` row combining the Global Market Score, ETF flow
proxy and Whale Intelligence snapshot that grounded that report's prompt.

### What was actually verified live

Every new engine was run against real Postgres with the real FRED-sourced
`US10Y` history synced during Sprint 2/3 testing:
- `/api/global-score` returned a real composite (institutional_activity=75
  because the ETF factor was genuinely triggered; crypto_strength=43 from
  real live BTC/ETH/SOL data).
- `/api/similar/US10Y` returned 5 real historical matches with real 1/3/7/30d
  forward returns (regime tags were `null` for most, honestly, since this
  sandbox never synced the full SPX/BTC/VIX/DXY set needed to reconstruct
  one -- exactly the documented degrade-gracefully behavior, not a bug).
- `/api/etf` returned 33 real, freshly-collected ETF-category news items,
  correctly classified bullish/bearish/neutral.
- `/api/whales` correctly reported unavailable with a clear reason.
- `/api/backtest` and creating a Knowledge Rule with the identical condition
  produced **identical results** (38 occurrences, 34.21% win rate) --
  confirming the rule engine actually calls the same backtest engine rather
  than a second implementation.
- `/api/brain` correctly 404s with no report yet, and `/api/brain/generate`
  correctly 503s without `OPENAI_API_KEY` -- the same honest-failure
  behavior as the pre-existing `/api/report/generate`.
- Migration 0009 was verified with a full upgrade/downgrade/upgrade cycle.
- 142 tests pass (36 new this sprint), `ruff check` clean.

## V2: Quant Hedge Fund Engine

Full repository inspection first (again), then extended -- nothing rewritten.
V2 decomposes the Sprint 9 "AI Brain" into a genuine multi-agent
architecture, adds long-term Market Memory, a Scenario Engine, a Conviction
Engine, an Explanation Engine, a Smart Alert Engine that pushes real deltas
to Telegram, a virtual Portfolio Engine, 8 new API endpoints, 7 new Telegram
commands and a browser dashboard.

### 1. Multi-Agent AI (Macro / Crypto / Equity / News / Sentiment / Reasoning)

Five specialist agents, each a thin orchestration layer over engines that
already existed -- no new data collection, no second LLM call per agent
(only the Reasoning Agent below calls an LLM, same as before):

- **Macro Agent** (`app/services/agents/macro_agent.py`) -- DXY/Gold/Silver/
  Oil/VIX/US10Y/US30Y/FEDRATE + the Global Score's liquidity/macro-pressure
  sub-scores. ECB/BOJ/PBOC policy and CPI/PPI have no configured live-quote
  source in this project (CPI/M2 are available historically via
  `/api/history` where synced) -- reported as out of scope, not guessed.
- **Crypto Agent** (`crypto_agent.py`) -- BTC/ETH/SOL/TOTAL/BTC.D + the
  existing Whale/ETF Intelligence engines (Sprint 9, unchanged).
- **Equity Agent** (`equity_agent.py`) -- indices + Magnificent 7. Sector
  rotation and market breadth are explicitly reported unavailable: this
  project only collects index/single-name price data, no sector
  classification or exchange breadth feed.
- **News Agent** (`news_agent.py`) -- wraps the existing News Engine's
  classified feed (not reclassified) and adds a deterministic market-impact
  estimate: `|sentiment_score| x category_weight`, with documented per-
  category weights (Fed/SEC/ETF/macro weighted above single-asset crypto/
  stock news) -- a transparent formula over real data, not a guess.
- **Sentiment Agent** (`sentiment_agent.py`) -- thin wrapper over the new
  `SentimentEngine`: a real, free, keyless Crypto Fear & Greed Index
  (`api.alternative.me`) blended with news sentiment via
  `weighted_average()`, renormalized over whichever components are actually
  available. Twitter/X, Reddit and options sentiment have no configured
  source in this project and are reported `"social_sentiment_available":
  false` with a clear reason -- never blended into the score as a guess.
- **Reasoning Agent** -- not a new engine: the existing `ReportGenerator`
  (Sprints 1-9) now also receives all five agents' outputs via
  `AgentOrchestrator` and synthesizes them into one narrative, instructed to
  call out disagreement between agents rather than just concatenating them.
  `/api/agents` exposes each agent's raw output independently.

Each agent also reports an optional `direction` (`"bullish"`/`"bearish"`/
`"neutral"`/`None`) and `confidence` (0-100/`None`) on its `AgentOutput`,
computed from data it already has -- Macro from `risk_on_score -
risk_off_score`, Crypto/Equity/Sentiment from their own 0-100 sub-score via
`direction_from_score()` (`app/services/common/scoring.py`, 50 = neutral),
News from its already-computed bullish/bearish item counts. `None` when the
underlying data is unavailable, never a guessed default. This feeds the
**Consensus Engine** (`app/services/consensus/engine.py`): a deterministic,
non-LLM vote tally across all five agents, weighted by each agent's
confidence (floored at 1.0 so a unanimous-but-low-confidence read still
counts as a real vote). An agent with no direction this cycle is excluded
from the tally entirely, not defaulted to neutral -- and if nothing
reported, the endpoint returns 503 rather than fabricating a 33/33/33
split.

```
GET /api/consensus
/consensus
```

### 2. Market Memory

`MemoryEngine` (`app/services/memory/engine.py`) is a read-only aggregator
across all 13 relevant persisted tables (predictions, signals, regime,
correlations, patterns, similarity, knowledge rules, whale, ETF, sentiment,
global score, news, macro events -- plus alerts, 14 total). Two gaps from
Sprint 9 were closed to make this genuinely complete: `WhaleIntelligenceEngine`
and `ETFIntelligenceEngine` gained `compute_and_store()` methods that persist
every read (including honest "unavailable" reads) to new `whale_snapshots` /
`etf_flow_snapshots` tables -- history is never lost, even when the answer is
"no data source configured".

```
GET /api/memory?category=&since=&limit=
/memory [category]
```

### 3. Scenario Engine

`compute_scenarios()` (`app/services/scenarios/engine.py`) generates four
named scenarios (Soft Landing / Risk Off / Liquidity Expansion / Black Swan)
whose probabilities always sum to exactly 100. Every weight is a documented,
deterministic function of the Global Market Score's already-computed
sub-scores -- Black Swan is structurally dampened (`x0.25`) rather than
capped, since a tail-risk scenario should read as rare by construction, not
just "whatever's left over".

```
GET /api/scenarios
/scenarios
```

### 4. Conviction Engine

`classify_conviction()` (`app/services/conviction/engine.py`) buckets any
confidence percentage into Weak/Medium/Strong/Very Strong/Institutional,
reusing Knowledge Rules' existing sample-size discount
(`compute_confidence_pct`) rather than a second formula. "Institutional"
additionally requires the underlying sample to actually be large --
a lucky one-off high-confidence read can reach at most "Very Strong". Gates
the Smart Alert Engine below (`alert_eligible` = Strong or above).

```
GET /api/conviction?symbol=BTC
/conviction [symbol]
```

### 5. Explanation Engine

`ExplanationEngine.build()` (`app/services/explanation/engine.py`) assembles
an evidence pack -- triggered indicators, macro drivers, historical examples
(from Similar Market Engine), supporting news (filtered to the signal's own
direction), risk factors (Global Score fear/macro-pressure) and an
alternative view (the second-most-likely scenario) -- entirely from data
other engines already computed. Feeds the Reasoning Agent's prompt; no
dedicated API endpoint (not requested, and its output is naturally part of
`/api/brain`'s synthesis).

### 6. Smart Alert Engine

`AlertEngine.check_and_broadcast()` (`app/services/alerts/`) runs seven pure
delta-detection functions (`detectors.py`) against the two most recent
stored readings of each relevant snapshot: regime change, BTC/NASDAQ
correlation break, DXY trend reversal, lopsided derivatives positioning
(only ever fires if a derivatives snapshot is actually available), ETF sentiment
turning bullish, liquidity score swings, and upcoming curated macro/policy
events. Every detection is conviction-classified and logged to
`alert_logs` (`broadcast` flag records whether it cleared the gate); only
Strong-or-above detections are pushed to Telegram, via a `broadcast_text()`
helper generalized out of the existing `broadcast_report()` (Sprint 8) so
the bot-session lifecycle isn't duplicated. Runs on the scheduler's
`ANALYSIS_INTERVAL_MINUTES` cadence, after regime/signal/global-score.

### 7. Portfolio Engine

`PortfolioEngine` (`app/services/portfolio/`) tracks virtual portfolios
against real live prices (a special `CASH` symbol prices at a fixed 1.0,
representing uninvested cash). Exposure is computed per this project's
existing `AssetClass` taxonomy (crypto/stock/index/macro -- Gold shows up
under macro, this project has no separate commodity class) plus `cash`.
Drawdown reuses `compute_max_drawdown_pct` from Sprint 9's Backtest Engine
(not reimplemented) over a portfolio daily-return series built from each
position's own synced daily history, weighted at *current* position sizes
(a documented simplification, not fabricated -- if any non-cash position
lacks synced history, drawdown is honestly reported unavailable rather than
computed on a partial basis). Portfolio Health Score blends data
completeness, diversification (1 - Herfindahl index on exposure shares) and
risk, via the same `weighted_average()` helper the Sentiment Engine uses --
renormalized over whichever sub-scores are actually available.

```
GET  /api/portfolio?name=main
POST /api/portfolio/positions   {"symbol", "quantity", "entry_price"}
DELETE /api/portfolio/positions/{id}
/portfolio [add SYMBOL QTY [entry_price]]
```

**Portfolio Advisor** (`app/services/portfolio/advisor.py`): turns
already-computed data into an actionable BUY/SELL/HOLD recommendation --
no new data source, no LLM. Combines the Signal Engine's macro-wide
bull/bear `net_score` with the Probability Engine's empirical, symbol-specific
up/down/flat split for agreement on a given symbol (an honestly-documented
limitation: `net_score` is market-wide, not per-symbol -- this project has
no per-asset technical signal engine, so the two are the closest independent
reads available). Only recommends BUY/SELL when both agree; otherwise HOLD.
Stop-loss/take-profit are volatility-scaled off the Historical Intelligence
Engine's own ATR (2x ATR stop, fixed 2:1 reward:risk), and position size is
risk-based (defaults to 1% of portfolio equity per trade) when a portfolio
is present -- never fabricated when ATR or equity data is missing.

```
GET /api/portfolio/advice/{symbol}?timeframe=1d&risk_pct=0.01
/advice SYMBOL [timeframe]
```

### 8. Web Dashboard

A dependency-free single-page dashboard (`app/static/dashboard/`, vanilla
HTML/CSS/JS, no build step, no framework) served at `/dashboard` via
FastAPI's `StaticFiles`. 16 pages (Overview, Macro, Crypto, Stocks,
Correlations, Historical Similarity, AI Brain, Probability, Scenarios,
Whales, ETF, Signals, Reports, Portfolio, Advice, Settings), each backed entirely by
`fetch()` calls to the real JSON APIs above -- an endpoint that 404s or
reports data unavailable renders that fact on the page, never a mock value.
Verified in a real headless-Chromium session: every tab renders without a
JS error, live BTC/ETH/SOL prices and the Global Market Score render
correctly on Overview, and adding a portfolio position round-trips through
the real API.

### What was actually verified live (V2)

- `/api/sentiment` returned a real Fear & Greed read (27, "Fear") blended
  with real news sentiment (47) into a global score of 35.
- `/api/scenarios` returned four probabilities summing to exactly 100 from
  a real Global Market Score.
- `/api/agents` returned all five agents' real output, including the
  Crypto Agent correctly surfacing a real ETF sentiment classification
  (`leaning_institutional_buying`) and an honest whale-data-unavailable
  reason.
- `/api/portfolio` correctly valued a BTC + CASH position against live
  prices, computed real exposure percentages and a Health Score, and
  honestly reported drawdown unavailable (no synced daily history for BTC
  in this sandbox) instead of fabricating one.
- Migration 0010 was verified with a full upgrade/downgrade/upgrade cycle.
- The dashboard was loaded in a real headless-Chromium session across all
  15 tabs with zero JavaScript errors.
- 201 tests pass (59 new this sprint), `ruff check` clean.

## V3: Institutional Research Platform

Full repository inspection first (again, per the standing rule), then
extended -- nothing rewritten. V3 was requested as a ten-phase "Global Data
Lake / Feature Engine / Research Lab" build; every phase below is mapped
onto a genuine extension of an existing Sprint/V2 engine rather than a
parallel implementation (`_REGIME_RISK_SPLIT`, `compute_forward_returns`,
`compute_backtest_metrics`, the Backtest Engine's row-loader and the Smart
Alert Engine's `AlertLog` table are all reused, not duplicated). Two scope
decisions were made explicitly with the user up front rather than guessed:
the Data Lake stays at daily/4h/1h (the timeframes this project can
actually validate) plus forex and a real-source-only economic calendar --
no 1m/5m/15m or options/futures, since no honest free source exists for
them in this project; and the AI Researcher's discovery step is fully
deterministic statistics, with an LLM used only to turn already-computed
findings into a readable note (never to judge or invent a finding).

### 1. Global Data Lake extension (forex + economic calendar)

`ForexHistory` (`app/database/models.py`) extends the existing
`HistoryRegistry`/sync/validation/gap-repair pipeline (Sprint 6) to 6 major
pairs -- no second sync path was written. `EconomicCalendarEngine`
(`app/services/calendar/`) stores only real dated events: FRED release
dates for CPI/PPI/NFP/GDP (`FredReleaseCalendarClient`, keyed by
`FRED_API_KEY`, already configured) and a small curated seed of the 8 real
2024 FOMC meeting dates -- deliberately not extended with guessed future
dates, since this project has no verified live source for them. No
forecast/consensus values are stored; none exist for free.

```
GET /api/calendar?days_back=&days_ahead=
```

### 2. Feature Engine

`FeatureEngine` (`app/services/features/`) computes a documented set of
derived features per symbol from data already synced by the History
Registry -- returns, momentum (7/14/30/90d), RSI, MACD, ATR, realized
volatility, drawdown, and (where a whale/ETF snapshot history exists)
whale-flow and ETF-flow momentum -- and persists each run as a
`FeatureSnapshot` JSON blob. A feature that isn't computable this cycle
(e.g. no whale history for that symbol) is simply absent from the blob,
never fabricated.

```
GET /api/features/{symbol}?compute=
```

### 3. Research Lab

`ResearchEngine.test_hypothesis()` (`app/services/research/engine.py`)
answers questions like "how does BTC move after CPI" by matching curated
calendar dates to real stored bars (`nearest_bar_index`, shared with the
Event Impact Engine below via `events_lookup.py`) and reusing Sprint 9's
`compute_forward_returns`/`compute_backtest_metrics` -- the same forward-
return math the Backtest Engine already uses, not a second formula. Returns
occurrence count, average/median/max gain/max loss and win rate; 404s
honestly if the event category is unknown or no bars exist yet.

```
GET /api/research?symbol=&event=&horizon=&timeframe=
/research SYMBOL EVENT [horizon]
```

### 4. Strategy Lab

`StrategyLabEngine` (`app/services/backtest/strategy_engine.py`) extends
the existing condition-based Backtest Engine (Sprint 9) with stop
loss/take profit exit simulation, position sizing, walk-forward validation
(splits history into folds, reused verbatim by the Ranking Engine below)
and Monte Carlo simulation -- a seeded bootstrap resample of the strategy's
own real historical trade returns, never a fabricated return. Reuses the
Backtest Engine's existing row-loading helper rather than a second data
path.

```
POST /api/strategy   {"target_symbol","conditions",...,"mode":"run"|"walk_forward"|"monte_carlo"}
/strategy SYMBOL SYMBOL:field:op:value [...] [horizon] [sl=X] [tp=X] [size=X] [mode=...]
```

### 5. Regime Classifier extension

`MarketRegime` (`app/services/analysis/regime.py`) gained seven new states
-- Bull, Bear, Accumulation, Distribution, Capitulation, Recovery, Sideways
-- as priority-ordered rules layered onto the existing detector, not a
replacement (`detect_regime()`'s new `whale_classification`,
`momentum_30d`, `previous_regime` parameters all default to `None` and are
fully backward compatible). Fixed a real latent bug while extending: the
Global Score Engine's `_REGIME_RISK_SPLIT` lookup would have raised
`KeyError` on every one of these seven regimes the moment `detect_regime()`
could return them, crashing `/api/global-score` and everything downstream
-- caught and fixed before it ever shipped. Accumulation/Distribution are
explicitly documented as a derivatives-positioning proxy (same caveat as
the existing Whale Engine), not literal on-chain accumulation.

```
GET /api/regime
/regime
```

### 6. Event Impact Engine

`EventImpactEngine` (`app/services/research/impact.py`) measures the real
average return at 24h/7d/30d after every stored occurrence of a curated
event category (Fed/CPI/PPI/NFP/GDP/halving/crash/regulatory/...), sharing
the same bar-matching helper as the Research Lab. Extends `/api/events`
rather than a new router.

```
GET /api/events/impact?category=&symbol=&timeframe=
```

### 7. AI Researcher

`AIResearcherEngine` (`app/services/research/researcher.py`) runs daily,
reusing the existing Smart Alert Engine's `AlertLog` history (Sprint 9/V2)
as its discovery source instead of writing a second anomaly detector --
discovery stays fully deterministic. An LLM (Gemini-preferred,
Anthropic/OpenAI/xAI-fallback, via the shared `generate_text()` helper
added to `app/llm/client.py`) only narrates the pre-computed discoveries
into a readable note; with no LLM key configured it degrades to a plain
discovery list rather than failing.

```
GET  /api/research/notes/latest
POST /api/research/notes/generate?window_hours=
```

### 8. AI Hypothesis Engine

`HypothesisEngine` (`app/services/hypothesis/`) auto-generates comparison
hypotheses from a small template set (e.g. "BTC reacts stronger to FOMC
than to CPI") across BTC/ETH/SPX/NASDAQ, tests each side through the
Research Lab's own `test_hypothesis()`, and reaches a deterministic
accept/reject/inconclusive verdict via a fixed magnitude-margin comparison
(`evaluate_comparison()`) -- never an LLM's judgment call. Runs weekly on
the scheduler.

```
GET  /api/hypothesis
POST /api/hypothesis/test   {"symbol","event_a","event_b"}
POST /api/hypothesis/test-all
/hypothesis [SYMBOL EVENT_A EVENT_B]
```

### 9. Ranking Engine

`RankingEngine` (`app/services/ranking/`) ranks each of the six factors
that already drive the Signal Engine's confidence score (RSI, momentum,
volatility, correlation, whale flow, regime alignment -- `etf_inflow` is
honestly excluded, since no historical snapshot table backs it yet) by
real predictive edge. Reuses the Strategy Lab's own `walk_forward` with
`folds=2`: the older fold doubles as "historical importance", the newer
fold as "current importance", avoiding a second backtest implementation.

```
GET /api/ranking?symbol=&compute=
/ranking [SYMBOL]
```

### 10. Executive Dashboard extension

Two new pages added to the existing 15-page dashboard (`app/static/
dashboard/`, still dependency-free vanilla JS): **Research Lab** (daily AI
note + manual generate, factor ranking table, hypothesis list/test form,
event-research query form) and **Strategies** (a condition-builder that
drives `/api/strategy` in all three modes). Verified with `node --check
app.js` (syntax only) -- unlike the original 15 pages, these two were
**not** verified in a live headless-Chromium session in this sandbox (no
running Postgres/Redis available at the time), which remains an open
verification gap for a future session with a live stack.

### What was actually verified (V3)

- The `_REGIME_RISK_SPLIT` `KeyError` bug was caught and fixed before any
  of the seven new regimes could reach `/api/global-score` in production.
- The hand-implemented Dickey-Fuller/cointegration math was checked against
  a live one-off script with known stationary/non-stationary/cointegrated
  synthetic series before the tests were finalized.
- Migrations 0011-0016 each carry a real, reviewed `upgrade()`/`downgrade()`
  (the regime-enum migration's downgrade is a documented no-op --
  PostgreSQL has no `DROP VALUE` for enum types).
- 328 tests pass (94 new this sprint), `ruff check` clean.
- No new environment variables or Docker/compose services were needed --
  V3 reuses every existing key (`FRED_API_KEY`, `ANTHROPIC_API_KEY`/
  `OPENAI_API_KEY`, `COINGLASS_API_KEY`) and every
  existing process type (`app`, `bot`, scheduler jobs in-process).

## V4: Institutional AI Market Intelligence Platform (in progress)

A full architecture gap analysis was run against a 14-phase "institutional
platform" brief before writing any code (Brain Orchestrator, Market
Watchdog, Market State Engine, Volatility Detection, Consensus completeness,
multi-horizon Self-Learning, richer Historical Intelligence similarity,
Portfolio allocation, Explainable AI, Telegram terminal commands,
performance/observability). Verdict: 1 capability already fully built but
never wired up, 9 partially built, 1 genuinely missing. Full evidence trail
(file:line citations) published as an artifact; implementation proceeds
increment by increment, reusing every engine found rather than rebuilding it.

### Increment 1: wire up the orphaned Explanation Engine + fill Telegram/API gaps

`ExplanationEngine` (`app/services/explanation/engine.py`) was fully built
in an earlier sprint but never reachable from anywhere -- zero references
outside its own file, no API route, no Telegram command. Fixed:

```
GET /api/explanation/{symbol}
/why [symbol]
```

Also closed from the Telegram-command gap list: `/status` (last-computed
timestamps for Signal/Regime/Global Score, so staleness is visible rather
than guessed), `/health` (liveness check), `/risk` (composes the Global
Score's already-computed risk-on/off, fear and macro-pressure sub-scores
with the Signal Engine's conviction tier -- no new number, just an honest
view already-computed data), and `/scenario` (singular alias of the
existing `/scenarios`).

`ConsensusResult` (`app/services/consensus/engine.py`) gained
`conflict_pct` -- simply `100 - agreement_score` made explicit, not a new
measurement, so a caller doesn't have to derive "how split are the agents"
themselves.

416 tests pass (16 new), `ruff check` clean.

### Increment 2: Volatility Detection -- 3 new Smart Alert types from data already collected

The audit found ATR, volatility, funding-rate momentum and open-interest
change were all already computed and stored (Historical Intelligence
Engine, Feature Engine) but nothing read them to flag an abnormal move.
Three new pure detectors added to `app/services/alerts/detectors.py`,
wired into the existing `AlertEngine.check_and_broadcast()` cycle
alongside the 7 that already existed:

- **`flash_crash` / `flash_rally`** -- `AssetPrice.change_pct_24h` past an
  8% threshold (already computed by every price provider).
- **`funding_shift`** -- a swing in the Feature Engine's
  `funding_rate_momentum_pct` (already derived from the same derivatives
  snapshots `WhaleIntelligenceEngine` persists).
- **`oi_spike`** -- a swing in the Feature Engine's
  `open_interest_change_pct`, same source.

No new data source, no new provider call. `Breakout`/`Breakdown` and
`Large Liquidations` remain genuinely missing -- the former needs a
price-range comparison not yet built, the latter needs actual liquidation
event data this project has no configured source for (never faked).

426 tests pass (10 new), `ruff check` clean.

## Known operational limitation: Yahoo Finance

Plain `yfinance` scrapes Yahoo Finance's undocumented endpoints -- there is
no official free stock/commodity API without registration. **During this
build, this exact issue surfaced in testing**: Yahoo Finance persistently
returned HTTP 429 / empty responses to this sandbox's shared egress IP, even
after retries with backoff. This is a well-known, widely reported failure
mode for `yfinance` running from shared/datacenter/proxy IP ranges -- it is
not a bug in this code, and it may or may not affect your deployment host.

Indices/stocks/DXY/Gold/Silver are no longer sourced from `yfinance` alone.
`MultiSourceStockProvider` and `MultiSourceMacroProvider`
(`app/services/market/multisource_stocks.py`, `multisource_macro.py`) try a
fallback chain per symbol -- Twelve Data first (`TWELVEDATA_API_KEY`), then
Alpha Vantage for the Magnificent 7 only (`ALPHAVANTAGE_API_KEY`, indices
have no honest Alpha Vantage substitute), then the existing `yfinance` path
as a last resort, then honestly "not available." Each symbol's `source`
field and a `logger.info` line at fetch time record which provider actually
supplied it, so a blocked `yfinance` no longer means blocked data as long as
one key is configured. Consequences and mitigations already built in:

- Because of the aggregator's fault-tolerance, a fully-blocked chain (all of
  Twelve Data, Alpha Vantage and Yahoo Finance failing) never breaks the
  pipeline -- crypto (CoinGecko) and FRED's macro indicators (Fed Funds
  Rate, VIX, US10Y, US30Y) keep flowing regardless, and every downstream
  phase (correlations, regime, signals, reports) degrades gracefully rather
  than crashing when NASDAQ/SPX/DXY/GOLD/SILVER are unavailable.
- `download_last_two_closes()` (`app/services/market/yfinance_utils.py`)
  retries only the tickers still missing from a partial batch, up to 4
  attempts with backoff, instead of retrying the whole batch.
- Both Twelve Data and Alpha Vantage responses are cached in Redis
  (`RedisCooldownCache`) to stay within their free-tier daily/per-minute
  quotas without abandoning the existing polling cadence.

## Running locally

### Option A: Docker Compose (recommended)

```bash
cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN / GEMINI_API_KEY / COINGECKO_API_KEY / FRED_API_KEY
# (FRED_API_KEY is free: https://fred.stlouisfed.org/docs/api/api_key.html)
# optionally also: TWELVEDATA_API_KEY / ALPHAVANTAGE_API_KEY / COINGLASS_API_KEY
# -- see .env.example and the Yahoo Finance limitation section below
docker compose up --build
```

This starts Postgres, Redis, runs `alembic upgrade head`, then three
services: `app` (FastAPI + scheduler) on `http://localhost:8000`, and `bot`
(the Telegram long-polling process). The bot only needs `TELEGRAM_BOT_TOKEN`
to receive commands; set `TELEGRAM_BROADCAST_CHAT_IDS` too if you want
scheduled reports pushed automatically.

To backfill the Historical Intelligence Engine (a one-off, not part of the
default startup):

```bash
docker compose --profile history run --rm history-sync
```

### Option B: Local Python

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env   # point DATABASE_URL / REDIS_URL at your local services

alembic upgrade head
uvicorn app.main:app --reload          # API + scheduler
python -m app.telegram.main            # Telegram bot (separate process, optional)
```

### Verifying it works

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/market
curl http://localhost:8000/api/btc
curl "http://localhost:8000/api/market/BTC/history?days=7"
curl http://localhost:8000/api/news
curl "http://localhost:8000/api/news?category=crypto&limit=10"
curl http://localhost:8000/api/correlations
curl http://localhost:8000/api/regime
curl http://localhost:8000/api/signals
curl http://localhost:8000/api/report
curl -X POST http://localhost:8000/api/report/generate   # requires OPENAI_API_KEY
curl "http://localhost:8000/api/history/BTC?timeframe=1d&limit=10"   # requires sync_history.py to have run
curl http://localhost:8000/api/events
curl "http://localhost:8000/api/probability/BTC?timeframe=1d"
curl "http://localhost:8000/api/patterns/BTC?timeframe=1d"
curl "http://localhost:8000/api/knowledge/BTC?timeframe=1d&k=5"
curl http://localhost:8000/api/brain                                  # alias of /api/report
curl "http://localhost:8000/api/similar/BTC?timeframe=1d&k=25"
curl http://localhost:8000/api/global-score
curl http://localhost:8000/api/etf
curl http://localhost:8000/api/whales
curl -X POST http://localhost:8000/api/backtest -H "Content-Type: application/json" -d \
  '{"target_symbol":"BTC","conditions":[{"symbol":"BTC","field":"rsi","operator":"lt","value":30}]}'
curl http://localhost:8000/api/knowledge/rules
curl http://localhost:8000/api/agents
curl http://localhost:8000/api/memory?limit=20
curl http://localhost:8000/api/scenarios
curl http://localhost:8000/api/sentiment
curl http://localhost:8000/api/liquidity
curl http://localhost:8000/api/conviction
curl http://localhost:8000/api/portfolio
curl -X POST http://localhost:8000/api/portfolio/positions -H "Content-Type: application/json" -d \
  '{"symbol":"BTC","quantity":0.5,"entry_price":60000}'
```

Full interactive API documentation (every endpoint, params, response
schemas) is auto-generated by FastAPI at `http://localhost:8000/docs`. The
browser dashboard is at `http://localhost:8000/dashboard/`.

The scheduler runs every collector/analyzer immediately on startup, then on
its own interval:

| Job | Interval |
|---|---|
| Market data collection | `MARKET_DATA_INTERVAL_MINUTES` (default 5) |
| News collection | `NEWS_COLLECTION_INTERVAL_MINUTES` (default 10) |
| Correlations, regime, signals | `ANALYSIS_INTERVAL_MINUTES` (default 30) |
| Global Score, Sentiment, Scenarios, Whale/ETF snapshots, Alert check | `ANALYSIS_INTERVAL_MINUTES` (default 30) |
| General report + broadcast | `REPORT_INTERVAL_MINUTES` (default 30) |
| Session reports (Asia/Europe/Morning/US Open/Daily Summary) | fixed UTC cron times, see `app/scheduler/jobs.py` |

### Tests

```bash
pytest
ruff check .
```

201 tests cover every pure-logic path: sentiment classification, correlation
math, regime rules, signal scoring, report prompt construction, Telegram
formatters and Markdown-fallback behavior, both aggregators' fault-tolerance
(partial and total failure), the historical intelligence engine's technical
indicators, gap/duplicate detection, resampling and symbol registry, the
probability engine's forward-return bucketing, the pattern engine's
candlestick/crossover detectors, the knowledge engine's nearest-analog
search, the Sprint 9 backtest metrics/condition DSL, the Global Market
Score's deterministic formula, the Similar Market Engine's historical-regime
reconstruction, the Self-Learning Engine's direction comparison, the
Knowledge Rules confidence formula, the V2 sentiment/scenario/conviction/
portfolio pure-function math, the alert detectors' delta logic, the
explanation engine's evidence assembly (mocked dependencies, no DB), and a
DB-free smoke test that every FastAPI router (including route-ordering for
`/api/knowledge/rules` vs `/api/knowledge/{symbol}`) is actually mounted.
Every phase was additionally verified live against a real Postgres + Redis
instance during development (see commit history for the specific checks
performed per phase), and V2's dashboard was verified in a real headless-
Chromium session.

## Further documentation

- [`docs/API.md`](docs/API.md) -- full endpoint reference (also live at `/docs` on a running instance)
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) -- Railway + Docker Compose deployment guide, including every real pitfall hit and fixed during this project's actual rollout

## Configuration

See `.env.example` for the full list. Nothing except infrastructure URLs
(`DATABASE_URL`, `REDIS_URL`) has a hardcoded secret default -- every API
key is optional-per-provider: a provider missing its key raises a clear
error that's logged and skipped, rather than fabricating data.

| Variable | Required for | Notes |
|---|---|---|
| `DATABASE_URL` | everything | defaults to the docker-compose Postgres |
| `REDIS_URL` | caching | defaults to the docker-compose Redis |
| `COINGECKO_API_KEY` | crypto data | optional; raises your rate limit |
| `FRED_API_KEY` | Fed rate, VIX, US10Y/30Y, Oil | free key required |
| `TWELVEDATA_API_KEY` | indices, Magnificent 7, DXY/Gold/Silver | optional; primary link of the fallback chain, free tier 800 req/day |
| `ALPHAVANTAGE_API_KEY` | Magnificent 7 fallback, news sentiment fallback | optional; free tier 5 req/min, 25/day |
| `COINGLASS_API_KEY` | funding rate, open interest, liquidations, long/short ratio | optional; primary derivatives source, free tier -- unconfigured falls back to CoinGecko's keyless `/derivatives` endpoint (funding rate + open interest only) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot | required to run `app.telegram.main` |
| `TELEGRAM_BROADCAST_CHAT_IDS` | automatic report broadcast | comma-separated chat IDs |
| `GEMINI_API_KEY` | AI analysis / `/report` | required for report generation, unless `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `XAI_API_KEY` is set; preferred provider, genuine ongoing free tier |
| `GEMINI_MODEL` | AI analysis | default `gemini-flash-latest` (a floating alias -- pinned Gemini model names get deprecated for new API keys without warning) |
| `ANTHROPIC_API_KEY` | AI analysis / `/report` | optional; second choice, tried when Gemini is unconfigured or fails |
| `ANTHROPIC_MODEL` | AI analysis | default `claude-sonnet-4-5-20250929` |
| `OPENAI_API_KEY` | AI analysis / `/report` | optional; third choice, tried when Gemini/Anthropic are both unconfigured or fail |
| `OPENAI_BASE_URL` | AI analysis | any OpenAI-compatible endpoint |
| `OPENAI_MODEL` | AI analysis | default `gpt-4o-mini` |
| `XAI_API_KEY` | AI analysis / `/report` | optional; last-resort fallback, or the only provider if Gemini/Anthropic/OpenAI are all unconfigured |
| `XAI_BASE_URL` | AI analysis | default `https://api.x.ai/v1` (OpenAI-compatible) |
| `XAI_MODEL` | AI analysis | default `grok-4.5` |
| `MARKET_DATA_INTERVAL_MINUTES` | scheduler | default `5` |
| `NEWS_COLLECTION_INTERVAL_MINUTES` | scheduler | default `10` |
| `ANALYSIS_INTERVAL_MINUTES` | scheduler | default `30` |
| `REPORT_INTERVAL_MINUTES` | scheduler | default `30` |
