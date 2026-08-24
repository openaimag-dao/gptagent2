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

### Increment 3: cooldown gating + `/watchdog`

The audit found the Smart Alert Engine already gated broadcasts by
conviction tier but had no time-based cooldown -- a metric oscillating
right around its threshold could re-fire the same alert every cycle.
Fixed with a second gate: an `alert_type` that already broadcast within
60 minutes is still logged (Market Memory's audit trail stays complete)
but not re-sent to Telegram (`_is_on_cooldown()` in
`app/services/alerts/engine.py`). `AlertEngine.check_and_broadcast()`'s
own contract is unchanged -- every detection is still logged, only the
already-optional `broadcast` flag is affected.

`/watchdog` surfaces the last 10 detections (sent or suppressed) by
reusing the existing `MemoryEngine`'s `alerts` category -- no new query,
no new table.

```
/watchdog
```

432 tests pass (6 new), `ruff check` clean.

### Increment 4: AI Brain Orchestrator -- one pipeline instead of five islands

The audit found every piece of the requested "collect -> agents -> consensus
-> scenarios -> portfolio -> report -> memory" pipeline already existed, but
`ReportGenerator.generate_and_store()` (the closest thing to a Brain) never
called Consensus, Scenarios, or Portfolio Advice -- they were each only
reachable through their own isolated API route or Telegram command. Wired
together, reusing already-computed data rather than re-running anything:

- **Consensus**: `compute_consensus()` runs over the exact `AgentOutput`s
  already fetched this cycle -- no second agent run.
- **Scenarios**: `compute_scenarios()` runs over the exact `GlobalMarketScore`
  row already computed this cycle -- no second Global Score computation.
- **Portfolio Advice**: a best-effort BTC/daily read via the existing
  `PortfolioAdvisorEngine` (wrapped in the same try/except pattern already
  used for the Knowledge Engine and Agent Orchestrator -- an optional
  enrichment failing never fails the whole report).

All three are additive keys on the existing `institutional_summary` JSON
field (`consensus`, `scenarios`, `portfolio_advice`) -- the API/Telegram
contract for `/report` is unchanged, existing consumers of the other keys
are unaffected.

**Store Memory**: `MemoryEngine` already aggregated 14 tables read-only but
never included the `Report` table itself -- the actual "final intelligence"
artifact from each cycle was invisible to `/memory`. Added as a 15th
category (`reports`), closing the last step of the pipeline the brief asked
for without inventing a new write path (the Report row already existed;
this just makes it discoverable alongside everything else).

432 tests pass (0 new -- `compute_consensus`/`compute_scenarios` already had
unit coverage; `ReportGenerator.generate_and_store()` itself is verified
live against real Postgres + a real LLM call, matching this project's
established test convention for DB-and-LLM-heavy orchestration methods),
`ruff check` clean.

### Increment 5: Market State Engine -- 3 new regimes, 3 new sub-scores

The audit found 13 regime labels and 9 named sub-scores already existed,
but 3 requested regimes and 3 requested sub-scores had no analog. Added,
reusing data already collected -- migration `0017`:

- **Strong Bull** -- BTC and SPX 30d momentum both >=20% (double Bull's
  >=10% threshold).
- **Bull Weakening** -- momentum still positive but decelerated by more
  than 5 points since the previous `FeatureSnapshot` reading (needed a new
  `previous_momentum_30d` comparison in `RegimeDetector`, fetching the
  second-most-recent snapshot per symbol -- same `_last_two()`-style
  pattern the Smart Alert Engine already uses).
- **Altseason** -- BTC dominance (`BTC.D`) falling >1% while both ETH and
  SOL rally >3% -- capital rotating from BTC into alts, tracked via 3 new
  `regime_inputs` fields (`btc_dominance_change_pct`, `eth_change_pct`,
  `sol_change_pct`).

`GlobalScoreEngine` gained 3 nullable sub-scores (honestly `None`, never a
fabricated neutral default, when the underlying data isn't ready yet):

- **`trend_strength_score`** -- magnitude of the 30d trend regardless of
  direction, from the same `momentum_30d` the Bull/Bear rules already use.
- **`risk_score`** -- a single blended read over `risk_off_score`,
  `fear_score` and `macro_pressure_score` via the existing
  `weighted_average()` helper (not a new measurement, a composite of
  numbers the engine already produces).
- **`confidence_score`** -- the Signal Engine's own `confidence_pct`,
  surfaced here too rather than recomputed.

Also fixed the same class of bug V3 caught before shipping: `_REGIME_RISK_SPLIT`
is an exhaustive dict keyed by `MarketRegime` -- the 3 new regimes were
added to it (and to the risk-level classification in `ReportGenerator`)
before they could reach production and `KeyError`.

Since `market_regime_type` is a native Postgres enum and `global_market_scores`
gets new columns, this needs migration `0017` (`ALTER TYPE ... ADD VALUE`
+ 3 nullable `ADD COLUMN`s, same reversibility caveat as the V3 regime
migration -- Postgres has no `DROP VALUE`). Since this project's database
has no public network access (same reason `/api/admin/sync-history`
exists), a matching `/api/admin/migrate` endpoint was added to apply
migrations the same way: triggered over HTTP from outside, run by the
container itself.

445 tests pass (13 new), `ruff check` clean, migration SQL verified via
`alembic upgrade head --sql` (chains cleanly onto 0016).

### Increment 6: Agent Reliability -- Self-Learning feeds back into Consensus

The audit's last finding: `LearningEngine` measured real, honest accuracy
for probability predictions, but was never consulted anywhere agent
weighting happens -- `ConsensusEngine` weighted every agent's vote purely
by its own self-reported confidence, with no track record involved.

New `AgentReliabilityEngine` (`app/services/reliability/engine.py`, table
`agent_prediction_logs`, migration `0018`) closes this using the exact
same pattern `LearningEngine` already established for probability
snapshots -- log a call, wait for its horizon to elapse in real synced
history, then check what actually happened:

- Every time `ConsensusEngine.compute()` runs, each agent's direction call
  is logged against BTC's latest synced daily close (the same macro-proxy
  every agent's direction already speaks to -- documented in the module's
  own docstring, not a new claim of per-symbol precision).
- `evaluate_reliability()` checks every previously-logged call whose 1-day
  horizon has now elapsed against the real realized return, reusing
  `LearningEngine.realized_direction()` rather than reimplementing "what
  actually happened" a second time -- returns `{agent_name: accuracy_pct}`,
  with an agent simply absent (never a fabricated default) until it has at
  least one evaluable call.
- `compute_consensus()` gained an optional `reliability` parameter: when an
  agent has a real track record, its vote weight is scaled by that
  accuracy (a consistently-wrong agent counts for less over time); an
  agent with no track record yet keeps its raw confidence-only weight --
  fully backward compatible (default `None` preserves the exact prior
  behavior).
- Wired into both `ConsensusEngine` call sites (`GET /api/consensus`,
  `/consensus`); a reliability-tracking failure degrades to the old
  confidence-only weighting rather than breaking consensus entirely (same
  try/except pattern as the Knowledge Engine lookup in `ReportGenerator`).

456 tests pass (11 new), `ruff check` clean, migration SQL verified via
`alembic upgrade head --sql` (chains cleanly onto 0017).

### Follow-up: `/status` and `/risk` had no API route, so the dashboard had nothing to call

Live-verifying the finished v3.0 effort surfaced a real gap: `/status` and
`/risk` had been wired into Telegram only, breaking this project's own
established pattern where every Telegram command has a matching API
route (`/score` -- `/api/global-score`, `/consensus` -- `/api/consensus`,
`/why` -- `/api/explanation/{symbol}`, etc.). Added `GET /api/status` and
`GET /api/risk`, each independently building the same engines the
Telegram handler already does (matching how every other paired
API/Telegram capability in this project works).

Also added 4 dashboard pages that existed as capabilities but never had
anywhere to be seen: **Risk**, **Why** (calls `/api/explanation/{symbol}`
with a symbol input, same pattern as Advice/Learning), **Watchdog**
(reuses the existing `/api/memory?category=alerts` -- no new query), and
**Status**. The Consensus page also gained a `conflict_pct` bar next to
Agreement, matching what `/consensus` already prints in Telegram.

456 tests pass (2 new router-registration checks), `ruff check` clean,
`node --check app.js` clean.

## V4.0: Institutional Intelligence Expansion

A second, larger V4 effort followed the audit-driven increments above:
a 10-phase mega-spec ("transform GPTAgent2 into the world's most
intelligent AI Market Intelligence Platform") under the same standing
rule as everything else in this project -- never rewrite or duplicate an
existing module, extend only where a real capability gap exists, and
everything must be reachable via all three surfaces (API, Telegram,
dashboard). Phases 1-8 are complete, shipped and verified live; phases
9-10 (performance passes across the full platform, and this
documentation) close out the effort.

### Phase 1: Market Replay Engine

`app/services/replay/engine.py` (migration `0019`, table
`market_snapshots`) takes one consolidated snapshot per cycle --
regime, health/trend/risk/confidence scores, consensus, portfolio
advice -- and adds `diff_snapshots()` (a pure function comparing any two
snapshots) and `get_nearest(timestamp)`/`get_latest()` lookups. This
became the backbone for historical comparison everywhere else in V4
(Terminal's `/compare`, Weekly/Monthly review) rather than each later
phase re-deriving its own "what changed since" logic.

```
GET /api/replay, GET /api/replay/history, GET /api/replay/compare
/replay
```

### Phase 2: Breakout Intelligence

`app/services/breakout/engine.py` (migration `0020`, table
`breakout_events`) detects breakout/breakdown/retest/liquidity-sweep
events from price action already collected, cross-confirmed against
volume, ATR, VWAP, regime and multi-timeframe agreement -- each
confirmation flag independently `True`/`False`/`None` (never guessed
when the underlying signal isn't available).

```
GET /api/breakout/{symbol}
/breakout [symbol]
```

### Phase 3: OnChain Intelligence (honest scaffold)

`app/services/onchain/engine.py` reports on-chain metrics (netflow,
SOPR, MVRV, NUPL, TVL) only when a real configured data source backs
them -- this project has no free on-chain data provider wired in, so
every field honestly reports "unavailable" rather than fabricating a
number, matching the same honesty precedent as the ETF flow proxy and
Whale Intelligence from earlier sprints.

```
GET /api/onchain/{symbol}
/onchain [symbol]
```

**Update -- DefiLlama wired in (BTC/ETH/SOL TVL, stablecoin supply, DEX
volume):** `app/services/onchain/providers.py`'s `DefiLlamaClient` calls
DefiLlama's free, keyless API for real `tvl`/`stablecoin_supply`/
`dex_volume` per chain (cached 5 minutes via `RedisCooldownCache`).
`available` is now `True` whenever any of those come back this cycle,
same convention as `WhaleIntelligenceEngine`. Every downstream consumer
(ForecastEngine's Confidence Breakdown, Executive Summary's
`market_health.onchain_activity`, ExplainabilityEngine's On-chain row,
`WatchdogEngine.get_onchain_overview`, the dashboard's On-Chain
Intelligence page, `/onchain` in Telegram) already read
`available`/`reason`/`metrics` generically, so all of them reflect real
DefiLlama data with no changes needed in any of them. The remaining
wallet-level metrics -- exchange netflow/reserves, whale wallet
activity, active/new addresses, dormancy, SOPR, MVRV, NUPL, coin days
destroyed, large transfers, bridge activity -- still genuinely need
`GLASSNODE_API_KEY` or (for Solana) `HELIUS_API_KEY`, neither of which
this update fabricates or substitutes for.

### Phase 4: AI Investment Committee

`app/services/committee/engine.py` convenes the same 5 specialist
agents the Consensus Engine already runs, but produces a structured
verdict instead of a vote tally: majority decision, dissent percentage,
supporting/opposing evidence excerpts per agent, a minority opinion, and
a final recommendation with a stated conviction level. A post-deploy
bug was caught and fixed live: the evidence excerpt logic was quoting
raw markdown `*HEADER*` lines from agent summaries instead of skipping
them.

```
GET /api/committee
/committee
```

### Phase 5: Scenario Simulator (what-if)

`app/services/whatif/engine.py` runs named macro scenarios ("Fed cuts
50bps", "DXY drops 3%", "Nasdaq crashes 5%", ...) forward through the
same probability-weighted scenario math the Scenario Engine already
uses, reporting the impact on each tracked symbol. No new market model
-- an application of an engine that already existed to hypothetical
inputs instead of only the live read.

```
GET /api/whatif, GET /api/whatif/{key}
/whatif [key]
```

### Phase 6: Prediction Quality Lab

`app/services/quality/engine.py` computes Brier score, precision/recall,
a calibration curve and time-horizon accuracy breakdowns over the same
graded-prediction history the Self-Learning engine already produces.
`evaluate_predictions()` was extracted out of `app/services/learning/
engine.py` into a shared function so both engines join `ProbabilitySnapshot`
against real stored history exactly once, rather than each maintaining
its own copy of that join.

```
GET /api/quality
/quality
```

### Phase 7: Professional Telegram Terminal

`app/services/terminal/engine.py` composes engines this platform already
had into digest views instead of duplicating them. Critical Alerts,
Market Replay, Committee Opinion, Risk Dashboard and Portfolio Summary
already existed as their own commands (Smart Alert Engine, `/replay`,
`/committee`, `/risk`, `/portfolio`) -- this phase adds only the
genuinely new composite views:

- **Top Opportunities** -- a composite conviction score per symbol
  (BTC/ETH/SOL) from probability edge, breakout signal and portfolio
  advisor recommendation (`app/services/terminal/opportunities.py`);
  a symbol with zero available signals is skipped entirely rather than
  defaulted to neutral.
- **Daily Brief** -- Committee verdict, risk/liquidity read, Top
  Opportunities, portfolio health and market regime in one view.
- **Historical Comparison** -- a thin wrapper over Phase 1's
  `diff_snapshots()`/`get_nearest()`.
- **Weekly Review / Monthly Performance** -- period-scoped prediction
  accuracy and alert counts, broadcast automatically (Mon 06:00 UTC /
  1st-of-month 06:30 UTC) -- no weekly/monthly schedule existed
  anywhere in this project before this phase.

```
GET /api/terminal/{brief,opportunities,history,weekly,monthly}
/brief, /opportunities, /compare [days], /weekly, /monthly
```

562 tests pass, `ruff check` clean, `node --check app.js` clean.

### Phase 8: Configurable Alerts

The Smart Alert Engine's 10 detectors (`app/services/alerts/detectors.py`)
are fixed and global: same thresholds, same symbols, broadcast to every
configured chat. `app/services/alerts/rules.py` (migration `0021`, table
`alert_rules`) adds the complementary, user-driven half: a rule fires
when a metric *the user picked* (`price`, `probability_edge`,
`breakout_probability`, `risk_off_score`, `liquidity_score`) crosses a
threshold *the user picked*, and notifies only the chat that created it.
Every metric reading reuses an existing engine (`MarketRepository`,
`ProbabilityEngine`, `BreakoutEngine`, `GlobalScoreEngine`) -- no new
data fetching. There is no user/auth model anywhere in this platform, so
a rule's owner is its Telegram `chat_id`; fired rules are logged to the
existing `AlertLog` table (`alert_type` prefixed `custom_rule:`) so
Market Memory's audit trail covers both alert systems.

```
POST/GET /api/alerts/rules, DELETE /api/alerts/rules/{id},
GET /api/alerts/history, GET /api/alerts/metrics
/setalert SYMBOL METRIC OPERATOR THRESHOLD [COOLDOWN_MINUTES],
/myrules, /delalert RULE_ID, /alerthistory
```

587 tests pass, `ruff check` clean, `node --check app.js` clean.

### Phase 9: Performance -- parallelize independent per-cycle reads

Several engines were awaiting a chain of 2-5 independent reads --
different tables, different engines, no result depending on another's --
one after another, so a single cycle's latency was the sum of every call
instead of the slowest one. Every case below was verified independent
first (no shared mutable state, no ordering dependency) before switching
it to `asyncio.gather()`, matching the existing pattern this project
already used for its 5-agent orchestrator (`app/services/agents/
orchestrator.py`) and its multi-provider market/news aggregators:

- `TerminalEngine.compute_top_opportunities()` -- 3 engine reads per
  symbol x 3 symbols (9 sequential round-trips) now run as one gathered
  wave per symbol, and the 3 symbols themselves run concurrently too.
- `MarketReplayEngine.compute_and_store()` -- two clusters (assets/regime/
  global-score; portfolio-advice/whale/etf/news/probability, 3 and 5 reads
  respectively) gathered, preserving the existing try/except around the
  portfolio-advice call.
- `WhatIfSimulator._historical_impact()`'s per-symbol event-impact lookups,
  and `simulate()`'s regime/global-score/probability read cluster.
- `BreakoutEngine.compute_and_store()`'s three confirmation checks
  (regime, OI/funding, multi-timeframe).
- `CommitteeEngine.convene()` -- `run_all()` and `evaluate_reliability()`
  don't depend on each other, gathered instead of sequential.

No behavior change: same results, same error handling, same tests (587
pass unmodified) -- only the wall-clock cost of each cycle drops.

### Phase 10: Documentation

This section of the README, documenting Phases 1-9 above.

## V5.1: Autonomous Critical Market Alert System

A SECOND, independent alert layer alongside the Smart Alert Engine and
Configurable Alerts above -- neither is modified or removed by this
effort. Where those two require a human to define a rule (or ship a
built-in detector), this system decides for itself: it monitors 12
markets continuously and pushes a Telegram notification only when a
price move clears both a magnitude bar *and* a corroboration bar built
from signals this platform already computes. No user configuration
exists anywhere in this system by design.

`app/services/shocks/detectors.py` (pure, no I/O) and `app/services/
shocks/engine.py` (`CriticalAlertEngine`) implement it; table
`critical_alerts` (migration `0022`) tracks live episodes.

**Monitored assets**: BTC, ETH, SOL, Nasdaq, S&P 500, Dow Jones, DXY,
Gold, Oil, VIX, the 10-year Treasury yield, and the Crypto Fear & Greed
Index -- the same symbols the rest of the platform already tracks
(`app/services/market/`, `app/services/sentiment/`), read here rather
than fetched anew.

**Time windows -- an honest limitation, not an oversight**: prices are
collected every `market_data_interval_minutes` (5 minutes in production)
into a real historical time series (a new `SnapshotBatch`+`AssetPrice`
row set every cycle, never overwritten). 5 minutes is therefore the
finest window this system can honestly evaluate; the spec's 1-minute
window is not implemented, since supporting it would need a dedicated
per-minute poller this project doesn't have -- standing one up would
roughly 5x provider API call volume for a window no other engine would
ever use. Windows actually evaluated: 5m/15m/30m/1h/4h/24h.

**Detection**: each symbol has a 4-tier absolute-move threshold ladder
(info/important/high/critical, e.g. BTC 3/5/8/10%) checked across every
window; the worst tier that clears wins, shortest window breaking ties.
When >= 3 of (BTC, ETH, SOL, Nasdaq, S&P 500, Dow Jones) move the same
direction at `important`+ simultaneously, one combined Market Shock
alert fires instead of several individual ones (escalated one tier
beyond the worst individual reading).

**AI filtering ("Suppress low-quality alerts")**: before a detection can
notify, its raw tier is checked against a composite 0-100 quality score
built from 9 signals this platform already computes -- reused, not
recomputed: volume (the window's `AssetPrice.volume_24h` change),
realized volatility (stdev of the window's own price series), Market
Regime alignment (`RegimeDetector`), Trend Strength/Risk Score/Confidence
Score (`GlobalScoreEngine`), Consensus alignment and Committee alignment
(the 5-agent orchestrator run *once* per cycle -- `compute_consensus()`
and `convene_committee()` both derive from that single run, never a
second agent invocation), and (BTC/ETH/SOL only, best-effort)
Historical Similarity (`SimilarMarketEngine`). A low score can soften a
tier by one step; it can never upgrade a tier or suppress an
unmistakably large move outright.

**Escalation, not spam**: an ongoing episode is tracked by `alert_key`
(e.g. `shock:BTC:down`, `multi_asset_shock:down`). A worsening tier on
an active episode *edits* the existing Telegram message
(`app.telegram.broadcast.edit_text`, new -- the codebase had never
called `bot.edit_message_text` before this) instead of sending a new
one; a same-or-declining tier is suppressed outright (no DB write, no
Telegram call); an episode untouched for 2 hours is marked resolved so
the next detection starts a fresh message rather than reopening a stale
one.

**Alert priority**: INFO/IMPORTANT are logged (silent mode -- stored,
never sent) to the existing `AlertLog` table (`alert_type` prefixed
`critical_shock:`), so Market Memory/Watchdog's audit trail already
covers this system with zero new wiring there. Only HIGH/CRITICAL push
to Telegram.

```
GET /api/shocks/active, GET /api/shocks/history
/shocks
```

629 tests pass (42 new: detectors' threshold/tier/quality/escalation
logic, the engine's cooldown/escalation/duplicate-suppression paths per
this feature's explicit test requirements, and formatter coverage),
`ruff check` clean,
`node --check app.js` clean, `alembic history` confirms `0022` chains
onto `0021`.

### Example Telegram alerts

*Momentum alert (single symbol, HIGH tier):*

```
🚨 *MOMENTUM ALERT* (HIGH)

*BTC*: -9.50% (15m) -- now 60,000.00

Market Regime: Risk Off
Trend Strength: 60/100
Risk Score: 60/100
AI Confidence: 82%

Committee Verdict: SELL (moderate conviction)

Reasons: elevated volume; elevated volatility; consistent with the current market regime; agent consensus agrees; AI committee agrees

Recommendation:
High downside volatility. Avoid aggressive entries until stabilization;
consider tightening stops on existing longs.

Expected Scenarios:
- Risk Off (40%)
```

*Market shock (synchronized multi-asset move, CRITICAL tier):*

```
🆘 *MARKET SHOCK* (CRITICAL)

*BTC*: -6.20% (15m) -- now 60,000.00
*ETH*: -7.40% (15m) -- now 2,500.00
*SOL*: -11.10% (15m) -- now 100.00

Market Regime: Risk Off
Trend Strength: 55/100
Risk Score: 68/100
AI Confidence: 91%

Committee Verdict: SELL (high conviction)

Reasons: elevated volatility; consistent with the current market regime; agent consensus agrees; AI committee agrees; elevated risk conditions

Recommendation:
Extreme downside volatility. Avoid aggressive entries until stabilization;
consider tightening stops on existing longs.

Related Markets: BTC, ETH, SOL
```

## V5.3: TradingView MCP Integration

TradingView MCP as the **Institutional Technical Analysis Provider** --
a new provider slotted into the existing Provider Layer, not a
replacement for anything. Its job is not prices (the existing market
providers already do that); it's professional multi-timeframe technical
analysis, normalized before it ever reaches the AI Brain:

```
TradingView MCP -> TradingView Adapter -> Normalizer -> Provider Layer -> Event Bus -> Existing Engines
```

`app/services/technical/tradingview_client.py` (`TradingViewMCPClient`)
is the adapter -- optional, unconfigured by default (`tradingview_mcp_url`
/ `tradingview_mcp_api_key` in settings, mirroring the
`MultiSourceMacroProvider` pattern). `app/services/technical/
normalizer.py` normalizes either TradingView's raw JSON or this
project's own synced OHLCV history into one `NormalizedIndicators`
shape, so `app/services/technical/provider.py`
(`TechnicalAnalysisProvider`) -- the Provider Layer entry point -- never
cares which source answered. **Failover is automatic and honest**: no
MCP endpoint configured, or a configured one that errors, falls back to
indicators computed locally from this platform's already-synced
history; a symbol/timeframe neither source can answer returns `None`
rather than a fabricated reading. This is the same "never invent data"
discipline as the OnChain and Whale Intelligence engines.

### 1. Files Added

```
app/services/technical/__init__.py
app/services/technical/indicators.py       -- EMA, Bollinger Bands, VWMA, Stochastic RSI, ROC,
                                               Momentum, CCI, ADX, Pivot Points, Support/Resistance
app/services/technical/resampling.py       -- daily -> weekly candle resampling (ISO week grouping)
app/services/technical/tradingview_client.py -- TradingView MCP adapter (optional, honest fallback)
app/services/technical/normalizer.py       -- NormalizedIndicators + normalize_local/normalize_tradingview
app/services/technical/provider.py         -- TechnicalAnalysisProvider (the Provider Layer entry point)
app/services/technical/scoring.py          -- AI Technical Score (bullish/bearish/trend/momentum/
                                               volatility/breakout/breakdown/confidence)
app/services/technical/signals.py          -- signal-event detection + Smart Alert alignment logic
app/services/technical/engine.py           -- TechnicalAnalysisEngine (composes the above, persists snapshots)
app/services/agents/technical_agent.py     -- 6th AI Brain agent (TechnicalAgent)
app/api/technical.py                       -- GET /api/technical/{symbol}
alembic/versions/0023_v5_technical_analysis.py -- technical_analysis_snapshots table
tests/test_technical_indicators.py
tests/test_technical_resampling.py
tests/test_technical_normalizer.py
tests/test_technical_provider.py
tests/test_technical_scoring.py
tests/test_technical_signals.py
tests/test_technical_engine.py
```

### 2. Files Modified

```
app/config/settings.py            -- tradingview_mcp_url / tradingview_mcp_api_key (optional)
.env.example                      -- mirrored settings block
app/database/models.py            -- TechnicalAnalysisSnapshot model (interpreted fields only)
app/services/agents/orchestrator.py -- AgentOrchestrator gains a 6th agent (technical); every
                                        downstream consumer (Consensus/Committee/Replay/Critical
                                        Alerts) iterates agent_outputs generically, so none of them
                                        needed a single line changed
app/services/alerts/detectors.py  -- detect_technical_alignment() (11th Smart Alert detector)
app/services/alerts/engine.py     -- AlertEngine wires TechnicalAnalysisEngine, checks alignment
                                      every cycle alongside the existing 10 detectors
app/main.py                       -- registers technical_router
app/scheduler/jobs.py             -- compute_technical_analysis_job (every analysis_interval_minutes)
app/telegram/formatters.py        -- format_technical() (interpreted fields only)
app/telegram/handlers.py          -- /technical SYMBOL command
app/static/dashboard/index.html   -- "Technical Analysis" nav entry
app/static/dashboard/app.js       -- renderTechnical() page
tests/test_agents.py, tests/test_alert_detectors.py, tests/test_telegram_formatters.py,
tests/test_api_app.py             -- coverage for all of the above
```

### 3. New Provider

`TechnicalAnalysisProvider` (`app/services/technical/provider.py`), the
first provider in the Provider Layer built specifically to sit on top of
another optional MCP-style source rather than a REST market-data API.
Any future MCP or third-party analysis provider follows the same shape:
an adapter with a `.configured` property, a normalizer function that
maps its raw payload onto `NormalizedIndicators`, and honest `None` on
anything it can't answer.

### 4. New Events

`TechnicalBullish`, `TechnicalBearish`, `GoldenCross`, `DeathCross`,
`RSIOverbought`, `RSIOversold`, `MACDBullishCrossover`,
`MACDBearishCrossover`, `SupportBroken`, `ResistanceBroken`,
`TrendAcceleration`, `TrendWeakening` -- every event the mission asked
for, generated by `app/services/technical/signals.py` and fed into
`active_signals` on every `TechnicalAnalysisEngine.analyze()` call.
Two or more aligned events (e.g. RSI Oversold + MACD Bullish Crossover +
Support Held) additionally produce a `HIGH_CONFIDENCE_BUY` /
`HIGH_CONFIDENCE_SELL` alignment, which `detect_technical_alignment()`
turns into a Smart Alert broadcast to Telegram -- the mission's worked
examples, implemented directly.

### 5. Indicator Coverage

Collected: RSI, MACD, EMA, SMA (20/50/200), VWMA, ATR, ADX, CCI,
Momentum, ROC, Stochastic RSI, Bollinger Bands, Pivot Points, Support,
Resistance -- 15 of the mission's 19. Honestly scoped out rather than
faked: **Ichimoku, Parabolic SAR, SuperTrend** (meaningfully more complex
than this platform's existing indicator math for the value they'd add
over what's already collected) and **Volume Profile** (no intraday
volume-at-price data exists anywhere in this project's history sync).
Multi-timeframe: 1H/4H/1D are computed from this project's own synced
OHLCV history (`Timeframe.ONE_HOUR/FOUR_HOUR/DAILY`); 1W is a real
secondary computation (`resampling.py` groups stored daily candles by
ISO week -- not fabricated, genuinely derived); 1m/5m/15m/30m are only
ever answerable through a configured TradingView MCP endpoint, since no
intraday OHLCV data this granular is synced locally -- with no endpoint
configured, `get_indicators()` honestly returns `None` for those four
rather than inventing a reading. Symbol coverage: BTC/ETH/SOL plus the
indices/macro symbols already in the history registry (SPX, NASDAQ, DJI,
DXY, GOLD, VIX, ...); BNB/LINK/XRP/DOGE/ADA/AVAX/SPY/QQQ/RUSSELL/US10Y/
Oil are real gaps in what's synced locally -- a configured TradingView
MCP endpoint is the only path to cover them without duplicating this
project's history-sync infrastructure.

### 6. AI Enhancements

- **6th AI Brain agent** (`TechnicalAgent`): folds the technical read
  into `AgentOrchestrator.run_all()` alongside Macro/Crypto/Equity/News/
  Sentiment, so Consensus, Committee, Replay and Critical Alerts all see
  it automatically.
- **AI Technical Score**: bullish/bearish score, trend strength,
  momentum, volatility, breakout/breakdown probability and confidence,
  combined across every timeframe that actually returned data
  (`combine_multi_timeframe`) -- confidence scales down honestly when
  fewer timeframes are covered.
- **Smart Alerts**: `detect_technical_alignment()` is now the 11th Smart
  Alert detector, checked every `check_and_broadcast()` cycle.
- **Never exposes raw indicators**: `TechnicalAnalysisSnapshot` (the
  persisted model), `GET /api/technical/{symbol}`, `format_technical()`
  and the dashboard's Technical Analysis tab all surface only the
  interpreted score/probabilities/signals -- RSI/MACD/ATR/... numeric
  values are computed internally and never returned anywhere.

### 7. Performance Metrics

- **Cached**: `TechnicalAnalysisEngine.get_latest()` reads the most
  recent persisted `TechnicalAnalysisSnapshot` first; `GET /api/technical/
  {symbol}` and `/technical` only fall through to a fresh `analyze()`
  call on a cache miss.
- **Refresh cadence**: `compute_technical_analysis_job` runs on the
  existing `analysis_interval_minutes` scheduler cadence (not per
  request), matching "refresh only when candles close" for the daily/4h/
  1h timeframes this platform actually has closed-candle data for.
  Symbols computed per cycle: BTC, ETH, SOL, SPX, NASDAQ, DJI, DXY, GOLD,
  VIX.
- **No duplicate requests**: local computation reuses `app.services.
  history.repository.get_series` (already-synced rows, no new provider
  calls); the TradingView adapter is only ever called when actually
  configured.

### 8. Test Results

79 new tests (71 across the `technical` package's 7 modules + 2 for the
new `TechnicalAgent` + 3 for the new `detect_technical_alignment` Smart
Alert detector + 3 for `format_technical`'s never-expose-raw-indicators
contract), **708 total, all passing**. `ruff check app tests` clean,
`node --check app.js` clean. A genuine scoring bug was caught by this
suite before shipping: `_trend_structure()` in `scoring.py` originally
used strict `>` for price-vs-moving-average, so a price exactly at its
SMA read as 100% bearish instead of neutral -- fixed to treat equality
as neutral (0.5), confirmed by `test_score_timeframe_neutral_reading_
scores_near_50`.

## V5.4: Next Generation Market Watchdog

Upgrades Market Watchdog from an alert-history viewer into the central
**Market Monitoring Hub** -- one place that answers "what is happening in
the market RIGHT NOW?" -- while keeping every byte of the existing Watchdog
(alert history, cooldown, suppressed alerts, severity, timestamps, Telegram
delivery status) exactly as it was, just moved from the bare `/watchdog`
command to `/watchdog events` (see Files Modified). Nothing here duplicates
Replay/Committee/Consensus/Scenario/Risk's own calculations -- the new
`WatchdogEngine` (`app/services/watchdog/engine.py`) is a read-only
composition layer over their already-computed outputs, with exactly one
exception: `run_cycle()` runs the shared 6-agent orchestrator ONCE per its
own scheduler cadence (`compute_watchdog_snapshot_job`, same
`analysis_interval_minutes` cadence as Consensus/Committee/Scenario) and
persists the result to a new `WatchdogSnapshot` row, so every read (API,
Telegram, dashboard) is a cheap cached lookup rather than a fresh agent
run -- the exact `_cycle_context()` pattern v5.1's `CriticalAlertEngine`
established (one orchestrator run per cycle, reused for everything).

### 1. Files Added

```
app/services/watchdog/__init__.py
app/services/watchdog/detectors.py     -- pure change-detection (trend/confidence/risk/
                                           liquidity/volatility/committee/regime) + small
                                           classification helpers (market health, AI bias,
                                           freshness)
app/services/watchdog/provider_health.py -- honest Provider Status (CoinGecko/FRED/Binance/
                                           DefiLlama/Helius/Telegram/Database/Brain)
app/services/watchdog/engine.py        -- WatchdogEngine (the Market Monitoring Hub)
app/api/watchdog.py                    -- GET /api/watchdog (+/events/providers/market/ai/
                                           changes/performance)
alembic/versions/0024_v5_watchdog_hub.py -- watchdog_snapshots + watchdog_events tables
tests/test_watchdog_detectors.py
tests/test_watchdog_provider_health.py
tests/test_watchdog_engine.py
```

### 2. Files Modified

```
app/database/models.py            -- WatchdogSnapshot, WatchdogEvent models
app/services/shocks/detectors.py  -- extracted compute_window_changes() (shared windowing
                                      logic, previously private to CriticalAlertEngine) and
                                      promoted _direction_bucket -> regime_direction_bucket
                                      (public), both now reused by the Watchdog hub instead
                                      of being reimplemented
app/services/shocks/engine.py     -- _window_prices() now calls the extracted
                                      compute_window_changes() (identical behavior, no
                                      duplicate logic)
app/scheduler/jobs.py             -- compute_watchdog_snapshot_job, provider-health
                                      recording in collect_market_data_job,
                                      get_job_next_run()/get_scheduled_job_count() helpers
app/main.py                       -- registers watchdog_router
app/telegram/formatters.py        -- format_watchdog_dashboard/_market/_onchain/_ai/
                                      _changes/_providers/_performance (format_watchdog()
                                      itself is untouched -- still the alert-history view,
                                      now reached via /watchdog events)
app/telegram/handlers.py          -- cmd_watchdog gains subcommand routing
app/static/dashboard/index.html, app.js -- renderWatchdog() rebuilt into the full hub
tests/test_shock_detectors.py, tests/test_telegram_handlers.py, tests/test_api_app.py
                                   -- coverage for all of the above + the pinned bare-
                                      /watchdog test updated to /watchdog events
```

### 3. New Commands

```
/watchdog              Complete dashboard (Current Market Status, Market/Crypto/Macro/
                        On-Chain Overview, AI Status, What Changed, Provider Status,
                        Alert History)
/watchdog events        Alert history (the original /watchdog view, unchanged)
/watchdog providers      Provider health
/watchdog market         Current market/crypto/macro/on-chain state
/watchdog ai             Committee/consensus/expected scenario/highest risk/opportunity
/watchdog changes        What changed since the last Watchdog cycle
/watchdog performance    Cycle timing, memory, CPU load average, scheduled job count
```

Mirrored on the API (`GET /api/watchdog`, `/events`, `/providers`, `/market`,
`/ai`, `/changes`, `/performance`) and the dashboard's rebuilt Watchdog Hub
page.

### 4. New Watchdog Sections

- **Current Market Status**: current time, last update, next scan (a real
  APScheduler `next_run_time`, not a guess), scan duration (timed around
  `run_cycle()`), Market Health (derived from the Global Market Score),
  Brain/Replay/Committee/Consensus status (`ok`/`stale`/`unavailable`,
  timestamp-only freshness checks against each engine's own already-stored
  reading).
- **Market Overview**: regime, trend (bull/bear/neutral bucket, shared with
  v5.1's shock-alignment scoring), trend strength, momentum/volatility
  (from the existing v5.3 Technical Analysis Engine's BTC proxy read),
  confidence, risk score, liquidity score, Market Intelligence Score
  (`GlobalMarketScore.global_score`).
- **Crypto Overview**: BTC/ETH/SOL/BNB/LINK/ADA/AVAX -- price, 24h/1h/15m %
  (the 1h/15m windows reuse v5.1's exact nearest-neighbor windowing
  algorithm), trend, volume, momentum, AI bias. BNB/LINK/ADA/AVAX have no
  CoinGecko coverage in this codebase (only BTC/ETH/SOL are synced) --
  reported honestly `available: false`, never a fabricated price.
- **Macro Overview**: DXY/VIX/Gold/Oil/US10Y/US02Y/Nasdaq/S&P 500/Dow
  Jones/Russell 2000 -- direction, daily %, trend, and Impact on Crypto (a
  documented directional heuristic, e.g. "DXY up -> bearish for crypto",
  labeled as a heuristic, not a measured correlation). US02Y (2-year
  Treasury yield) isn't in FRED's synced series list (only 10Y/30Y are) --
  honestly `available: false`.
- **On-Chain Overview**: whale positioning/funding/open interest from the
  real `WhaleIntelligenceEngine` (CoinGlass/CoinGecko-derivatives) when
  configured; TVL and stablecoin supply are now real too, via
  `OnChainIntelligenceEngine`'s DefiLlama client (see the Phase 3 update
  above); exchange netflow still needs `GLASSNODE_API_KEY` (no
  wallet-level client exists in this codebase).
- **AI Status**: committee opinion, consensus split, prediction confidence,
  expected scenario, highest risk and biggest opportunity (the
  highest-probability bearish/bullish scenarios from the existing
  `ScenarioEngine`, with their own rationale strings) -- all read from the
  latest `WatchdogSnapshot`, never recomputed on request.
- **What Changed**: field-level diff (regime/trend strength/confidence/
  risk/liquidity/committee) between the two most recent `WatchdogSnapshot`
  rows, plus the human-readable auto-detected events below.
- **Provider Status**: CoinGecko/FRED (real, DB-backed: last successful
  `AssetPrice` write per source, a Redis consecutive-failure counter as
  "Reconnect Count"), Database (a live, timed `SELECT 1`), DefiLlama (a
  live, timed, free/keyless TVL fetch -- see the OnChain Intelligence
  Phase 3 update above; unlike CoinGecko/FRED, DefiLlama has no scheduler
  job feeding a "last write" timestamp to infer health from, and its
  public API documents no strict rate limit, so a live probe is both
  necessary and safe here), Telegram (configured + last successful
  `AlertLog` broadcast), Brain (configured + last `Report.generated_at`),
  Binance (no client exists in this codebase -- reported
  not-implemented), Helius (a settings key exists but no wallet-level
  client is wired in -- reported not-configured, matching
  `OnChainIntelligenceEngine`'s own honesty). CoinGecko/FRED health is
  still inferred from write recency rather than live-probed, since
  probing a metered free tier on every dashboard/Telegram request would
  make the status page itself a source of rate-limit risk.

### 5. Automatic Detection (Watchdog Events)

`app/services/watchdog/detectors.py` runs on every `run_cycle()`:
`MarketRegimeChanged`, `TrendStrengthIncreased`/`Decreased`,
`ConfidenceIncreased`/`Dropped`, `RiskIncreased`/`Reduced`,
`LiquidityShift`, `VolatilitySpike`, `CommitteeChanged` -- every event the
mission asked for, persisted to a new `WatchdogEvent` table (distinct from
`AlertLog`/`CriticalAlert` -- this is the hub's own changelog, not a third
alert-broadcast system). Telegram only fires for `MarketRegimeChanged`,
`ConfidenceIncreased`/`Dropped`, `RiskIncreased` and `CommitteeChanged`
("never spam"), each with its own 60-minute cooldown
(`WatchdogEvent.telegram_sent`). Market Shock detection is intentionally
NOT duplicated here -- v5.1's `CriticalAlertEngine` already owns that,
independently, on its own schedule.

### 6. Performance Impact

- **One agent-orchestrator run per Watchdog cycle**, not per request --
  every dashboard/Telegram/API read is a cached `WatchdogSnapshot`/
  `get_latest()`-style lookup.
- **No new provider calls**: Crypto/Macro Overview reuse
  `MarketRepository.get_latest()`/`get_history()` (already-synced rows);
  Provider Status reuses already-stored timestamps rather than live-pinging
  external APIs (except the local `SELECT 1` for Database).
- **Reused, not duplicated, windowing logic**: `compute_window_changes()`
  is the same nearest-neighbor algorithm v5.1 already validated, extracted
  into a shared function instead of being reimplemented for the hub.

### 7. Tests Added

45 new tests (14 detector unit tests, 11 provider-health tests, 16
WatchdogEngine tests covering every section plus `run_cycle()`'s
persistence/change-detection/Telegram-cooldown path, 3 for the extracted
`compute_window_changes()`/`regime_direction_bucket()`, and the pinned
bare-`/watchdog` Telegram test updated to `/watchdog events` plus a new
default-dashboard test), **753 total, all passing**. `ruff check app
tests` clean, `node --check app.js` clean, `alembic history` confirms
`0023 -> 0024 (head)`.

### 8. Deployment Verification

Migration `0024` applies `watchdog_snapshots` + `watchdog_events`;
`compute_watchdog_snapshot_job` runs on the existing `analysis_interval_minutes`
cadence alongside Consensus/Committee/Scenario. Verified live: `GET
/api/watchdog` (and every subcommand route), `/watchdog` and its six
subcommands in Telegram, the rebuilt Watchdog Hub dashboard page, and a
clean scheduler log line (`Watchdog snapshot computed: health=... regime=...
scan_duration_ms=...`) confirming the cycle runs without errors.

## V5.5: Autonomous Market Scanner & Smart Alert System

A 24/7 background scanner that discovers unusual market events across a
real Top-500-by-market-cap crypto universe and publishes them into the
existing Watchdog/Replay/AlertLog pipeline -- users never configure an
alert, and only meaningful (HIGH/CRITICAL) events reach Telegram. Built as
a new `app/services/scanner` package that reuses v5.1's escalation state
machine, AI-alignment scoring and `detect_multi_asset_shock`, and v5.4's
`WatchdogEngine.get_latest_snapshot()` for AI context, rather than
reimplementing any of them.

### 1. New files

```
app/services/scanner/__init__.py
app/services/scanner/provider.py   -- CoinGeckoMarketsClient (paginated /coins/markets)
app/services/scanner/universe.py   -- ScannerUniverse: cached Top-N + ALWAYS_INCLUDE merge
app/services/scanner/sectors.py    -- curated SECTOR_MAP (~100 symbols, 10 sectors) + breadth
app/services/scanner/breadth.py    -- compute_market_breadth() (rising/falling/gainers/losers)
app/services/scanner/detectors.py  -- pure detection functions (price/volume/volatility/
                                       breakout/sector-ecosystem), mirrors shocks/watchdog
                                       detectors' no-I/O discipline
app/services/scanner/engine.py     -- MarketScannerEngine: run_cycle() orchestrator.
                                       NEVER imports app.telegram (enforced by a source-scan
                                       test) -- publishes only, never notifies directly
app/services/scanner/notifier.py   -- send_scanner_notifications(): the ONLY module allowed
                                       to import app.telegram.*, invoked solely by the
                                       scheduler job
app/api/scanner.py                 -- GET /api/scanner (+/scans/detections/movers/sectors/
                                       pending/suppressed)
alembic/versions/0025_v5_market_scanner.py -- scanner_snapshots + scanner_alerts tables
tests/test_scanner_provider.py
tests/test_scanner_universe.py
tests/test_scanner_sectors.py
tests/test_scanner_breadth.py
tests/test_scanner_detectors.py
tests/test_scanner_engine.py
tests/test_scanner_notifier.py
```

### 2. Modified files

```
app/database/models.py            -- ScannerSnapshot, ScannerAlert models
app/services/shocks/detectors.py  -- detect_multi_asset_shock() generalized with
                                      symbols/min_count/min_tier/category params (all
                                      default to the original v5.1 hardcoded values, so
                                      v5.1's own call site and tests are unaffected) --
                                      reused verbatim by the scanner for "CRYPTO MARKET
                                      SHOCK" instead of being reimplemented
app/config/settings.py, .env.example -- scanner_interval_minutes (15), 
                                      scanner_universe_refresh_hours (24)
app/scheduler/jobs.py             -- compute_market_scan_job (run_cycle() then
                                      send_scanner_notifications()), registered on
                                      scanner_interval_minutes
app/main.py                       -- registers scanner_router
app/telegram/formatters.py        -- format_scanner_alert/_dashboard/_movers/_sectors/
                                      _detections
app/telegram/handlers.py          -- /scanner command + movers/sectors/detections/pending
                                      subcommands
app/static/dashboard/index.html, app.js -- new "Market Scanner" page (renderScanner())
tests/test_telegram_formatters.py, tests/test_telegram_handlers.py, tests/test_api_app.py
                                   -- coverage for all of the above
```

### 3. New database tables

- **`scanner_snapshots`**: one row per symbol per scan cycle -- price,
  change_pct_1h/24h, volume_24h, market_cap, market_cap_rank, sector,
  recorded_at. The scanner's own rolling history (used to compute realized
  volatility, flash-move windows, and period high/low), independent of
  `AssetPrice`.
- **`scanner_alerts`**: mirrors `CriticalAlert`'s exact shape/lifecycle
  (alert_key, category, tier, symbols, message, telegram_message_ids,
  active, data, first_triggered_at/last_updated_at/resolved_at) -- the
  scanner's own escalation-episode table, reusing v5.1's
  `decide_alert_action`/`gate_severity`/`should_notify` state machine
  against these rows instead of `CriticalAlert`'s.

### 4. Scanner architecture

```
CoinGeckoMarketsClient  -- paginated /coins/markets (price_change_percentage=1h,24h)
        |
ScannerUniverse         -- Top-500 + ALWAYS_INCLUDE (BTC/ETH/SOL/BNB/XRP/ADA/DOGE/
        |                  LINK/AVAX/TRX/TON), Redis-cached, 24h lazy refresh
        v
MarketScannerEngine.run_cycle()
        |-- fetch markets -> build readings (attach sector via SECTOR_MAP)
        |-- persist ScannerSnapshot rows; load bounded 30-day history per symbol
        |-- per-symbol: classify_price_event / detect_volume_multiple /
        |     detect_flash_move / detect_volatility_regime / detect_new_high_low /
        |     detect_range_breakout / detect_support_resistance_break
        |-- compute_market_breadth() + compute_sector_breadth() (cached in Redis, 1h TTL)
        |-- read AI context ONCE from WatchdogEngine.get_latest_snapshot() (no fresh
        |     agent-orchestrator run)
        |-- detect_multi_asset_shock() over the ALWAYS_INCLUDE crypto set -> 
        |     "CRYPTO MARKET SHOCK" (folds individual moves into one combined alert)
        |-- detect_sector_ecosystem_event() per sector -> "<SECTOR> ECOSYSTEM
        |     STRENGTHENING/WEAKENING" (requires >=2 independently corroborating movers)
        |-- score_alert_quality() -> gate_severity() -> decide_alert_action() against
        |     ScannerAlert (new/escalate/suppress) -- always logged to AlertLog
        |     (alert_type="scanner:<category>"), broadcast=False initially
        v
send_scanner_notifications()  -- the ONLY module touching app.telegram.*; formats via
        |                        format_scanner_alert(), flips AlertLog.broadcast=True
        v                        only on a confirmed send
     Telegram (HIGH/CRITICAL only)
```

### 5. Event flow

Every detection -- notified or not -- is logged to the existing `AlertLog`
table (`alert_type="scanner:<category>"`), the same integration pattern
v5.1's `CriticalAlertEngine` established for `critical_shock:*`. Since
`MarketReplayEngine` already reads `MemoryEngine.get_category("alerts", ...)`
(backed by `AlertLog`), Replay automatically picks up every scanner
detection with zero new plumbing -- satisfying "publish into Watchdog,
Replay" without a second integration path. Anti-spam (cooldown, duplicate
suppression, escalation instead of a second alert) is the exact
`ScannerAlert` state machine v5.1 already validated for `CriticalAlert`:
BTC +3% -> below the "important" gate, no alert; BTC +5% -> new "high"
alert; BTC +8% -> the SAME episode is updated (escalate), not a new
Telegram message.

### 6. Performance benchmarks

- **2 CoinGecko calls per cycle** for the full Top-500 universe (250-coin
  pages via `/coins/markets`), not 500 individual requests.
- **Breadth/sector-breadth cached in Redis** (1h TTL) -- dashboard/API/
  Telegram reads never trigger a fresh fetch between scan cycles.
- **Universe cached** with a 24h TTL (lazy refresh on miss), not re-fetched
  every 15-minute cycle.
- **Scan cadence is 15 minutes, not the mission's literal 1 minute** -- an
  intentional, documented scope decision: a 1-minute cadence would
  multiply CoinGecko calls (and stored `ScannerSnapshot` rows) ~15x for a
  500-coin universe with no corresponding gain, since CoinGecko's own
  `/coins/markets` granularity is hourly/daily, not minute-level. 1m/5m
  windows are honestly not offered (matches v5.1's "1-minute window
  omitted, not faked" precedent) -- only 15m/30m/1h/4h/24h, computed from
  the scanner's own stored history.

### 7. Test results

60 new tests (7 provider/universe/sectors/breadth tests split across
their own files, 10 pure-detector tests including the sector
self-corroboration fix, 7 `MarketScannerEngine` tests covering
standalone/multi-asset/escalation/AI-filter/never-imports-telegram, 5
notifier tests, 10 Telegram formatter tests, 5 Telegram handler tests),
**813 total, all passing**. `ruff check app tests` clean, `node --check
app.js` clean, `alembic history` confirms `0024 -> 0025 (head)`.

### 8. Deployment verification

Migration `0025` applies `scanner_snapshots` + `scanner_alerts`;
`compute_market_scan_job` runs on `scanner_interval_minutes` (15m)
alongside the existing scheduler jobs. Verified live: `GET /api/scanner`
(and every subroute), `/scanner` and its four subcommands in Telegram, the
new Market Scanner dashboard page, a clean scheduler log line (`Market
scan: N symbols scanned, M detections, K Telegram notification(s)`), and
scanner-originated `AlertLog` entries (`scanner:*`) visible via
`/api/watchdog/events`/`/api/memory?category=alerts` -- confirming
"never bypass Watchdog" end-to-end in production.

## V8.0: Become Indispensable

The architecture reached feature-completeness with V5.5. V8.0 is not a new
engine or a new package -- it is a composition pass across every existing
screen, API response and Telegram message, turning already-computed numbers
into explanations a trader can act on in under a minute. Every change below
reuses another engine's existing output; nothing was fabricated, and no new
external provider call or expensive recomputation was added anywhere.

### 1. Market Scanner -> AI Market Brief

`MarketScannerEngine.get_market_context()` is now the single source every
scanner alert draws from (its former subset wrapper, `_ai_context()`, was
deleted as dead code). Every price-event alert message now states the
volatility label, the % change since the previous scan (from the symbol's
own already-fetched history), and -- reusing `scenario_extremes()` -- the
expected scenario, main opportunity and main threat. `format_scanner_alert()`
renders all of it.

### 2. Watchdog -> Market Control Center

`WatchdogEngine.get_market_brief()` (new `GET /api/watchdog/brief`, and the
first section of `/watchdog` in Telegram/dashboard) answers five questions
directly from the same `current_status`/`what_changed`/`ai_status` sections
`/watchdog` already computes: is the market healthy, is risk increasing, did
AI change its opinion, what changed today, what needs attention now.

### 3. Committee & Consensus explanations

`ConsensusResult` now retains each agent's normalized vote weight
(`agent_weights`) instead of discarding it after tallying, exposing a
`strongest_agent` property. `CommitteeVerdict` gained `invalidation_risk`:
the majority-side agent with the lowest weight, and what dissent percentage
would result if it flipped -- a deterministic derivation from the same
tally, not a new signal.

### 4. Replay/Similar -> historical lesson narrative

`build_historical_lesson()` (`app/services/similar_market/engine.py`)
composes `SimilarMarketEngine.find_similar_periods()`'s K nearest analogs
and forward returns with the existing backtest math
(`compute_backtest_metrics()`, `compute_win_rate_pct()`) into a plain-
language answer: what happened, how similar, average outcome, probability,
typical duration (the longest forward horizon where a majority of matches
kept moving the same direction), and a one-sentence lesson. Wired into
`GET /api/similar/{symbol}` (`lesson` field), the `/similar` Telegram
command, and the dashboard's Historical Similarity page.

### 5. Institutional report structure

`build_institutional_report()` restructures a generated `Report` into
Executive Summary / Biggest Opportunity / Biggest Risk / Market Drivers /
Sector Rotation / Historical Comparison / AI Conclusion / What to Watch
Next -- template composition of the existing LLM narrative fields, plus
`scenario_extremes()` for Opportunity/Risk and
`MarketScannerEngine.get_latest_sector_breadth()` (already cached every scan
cycle) for Sector Rotation. No LLM prompt or schema change. Wired into
`GET /api/report` (`institutional_report` field), `/report` in Telegram,
scheduled report broadcasts, and the dashboard's Reports page.

### 6. Telegram alerts explain themselves

`format_critical_alert()` now states **How Unusual** a move is --
`historical_similarity_score()` was already computed into every critical
shock alert's `quality_components` but previously only surfaced as a bare
`>=60` threshold inside a generic "Reasons" bullet; it's now an explicit
percentage ("X% of similar historical moves continued down afterward --
what AI expects next"). On an escalation of an already-active alert it also
states **What Changed** (e.g. "escalated from HIGH to CRITICAL"), from the
same `CriticalAlert` row the engine already looks up to decide the
escalate/suppress action. `format_watchdog()` -- the oldest, previously
bare-bones AlertLog formatter -- now shows each entry's AI confidence
(`AlertLog.confidence_pct`, persisted on every alert but silently dropped by
`MemoryEngine`'s alerts-category summary until now).

### 7. Data quality audit

A systematic sweep for hardcoded "unavailable"/"n/a" placeholders where the
real value was already computed elsewhere found two concrete wiring gaps
(most existing honest-unavailable messages checked out as genuinely
correct): `GlobalMarketScore.risk_score`/`confidence_score` were persisted
on every row and already exposed by `/api/global-score`, but three sibling
call sites (`/api/risk`, Telegram `/risk`, the Explanation Engine's
`risk_factors`) built a subset dict from the same row and dropped them --
now included in all three. `TerminalEngine.compute_brief()`'s `health_score`
preferred a Market Replay snapshot value that is itself just a stale copy of
an earlier Global Score reading -- it now prefers the Global Score already
fetched in the same method call, falling back to the Replay snapshot only
when no score exists yet.

### 8. Test results & deployment verification

830 -> 847 tests, all passing across the six PRs; `ruff check app tests`
clean throughout (only pre-existing, unrelated findings untouched).
Verified live in Railway production post-deploy: `/api/watchdog/brief`,
`/api/report` (`institutional_report`), `/api/risk`
(`risk_score`/`confidence_score`), `/api/similar/BTC` (`lesson`),
`/api/scanner` (scenario/opportunity/threat context), `/api/consensus`
(`strongest_agent`), and `/api/committee` (`invalidation_risk`) all
returned real, non-fabricated data; the scheduled report-generation job ran
cleanly with no errors immediately after deploy.

## AI Forecast Center

A large hero card, always the first thing shown on the dashboard's Overview
page: a $ price target, an interpolated price path, a bucketed probability
distribution, an AI Consensus vote tally, Market Regime/Risk gauges, Key
Levels, "What can change the forecast," and a live countdown to the next AI
update -- built entirely out of numbers other engines already compute. New
package: `app/services/forecast/engine.py`.

### 1. The math (deterministic, never fabricated)

Two real inputs drive everything: `ProbabilityEngine`'s empirical
`avg_forward_return_pct` for the requested horizon (the mean), and ATR --
this project's one existing $-volatility primitive, already used by
Portfolio Advisor for stop/take-profit bands (the standard deviation).

- **Price target** = `current_price * (1 + avg_forward_return_pct / 100)`.
- **Price path** (Now/6h/12h/18h/24h for the 24h horizon; proportional
  checkpoints for 3d/7d/30d) interpolates the same mean return by
  `sqrt(time_fraction)` -- the standard assumption that a random walk's
  variance grows linearly with time.
- **Probability distribution** (4 $ buckets) is a normal approximation
  around the price target using ATR as volatility, via the standard normal
  CDF (`math.erf`, stdlib, no new dependency) -- documented in
  `compute_probability_distribution`'s own docstring as a transparent
  statistical model, not a black-box output.
- **24h/3d/7d/30d horizons** are just `horizon=1/3/7/30` on
  `ProbabilityEngine`'s existing `Timeframe.DAILY` (already calendar days)
  -- no new multi-horizon engine.

### 2. Reused, not rebuilt

- **Regime/risk/consensus/committee** context is read straight off the
  latest `WatchdogSnapshot` rather than re-invoking Consensus/Committee/
  Regime/GlobalScore from scratch.
- **Confidence** tier reuses `ConvictionEngine`'s `classify_conviction` --
  including its Prediction-Quality-Lab Brier-score fold-in -- unchanged.
- **Key Levels** reuse `TechnicalAnalysisEngine`'s own support/resistance.
- **"What can change the forecast"** reuses `EconomicCalendarEngine.
  get_upcoming()` and the Consensus/Committee `invalidation_risk` narrative.
- **Confidence Breakdown** (Technical/News/Sentiment/Macro/Whales/On-chain/
  Correlations) is honestly gated on real data availability: On-chain
  always reports unavailable today (`OnChainIntelligenceEngine` is a
  documented no-data-source scaffold) rather than a fabricated number.

### 3. New files

```
app/services/forecast/engine.py    -- ForecastEngine + pure math functions
app/api/forecast.py                -- GET /api/forecast/{symbol}?horizon=
                                       24h|3d|7d|30d, GET /{symbol}/history
alembic/versions/0026_forecast_center.py -- price_forecast_snapshots table
tests/test_forecast_engine.py
tests/test_forecast_api.py
```

### 4. Modified files

```
app/database/models.py           -- PriceForecastSnapshot (realized_price/
                                     error_pct/evaluated_at reserved, nullable,
                                     for the follow-up grading job)
app/services/probability/engine.py -- get_latest() gains an optional
                                     horizon filter
app/services/analysis/report.py  -- untouched; derive_risk_meter (new,
                                     in forecast/engine.py) layers an
                                     "Extreme" tier on top without changing
                                     derive_risk_level's existing contract
app/scheduler/jobs.py            -- compute_forecast_job, BTC only for now,
                                     on the existing analysis_interval_minutes
                                     cadence
app/main.py                      -- registers forecast_router
app/static/dashboard/app.js, style.css -- renderForecastCenter(), prepended
                                     inside renderOverview(); new .forecast-*
                                     glassmorphism/animation classes, scoped
                                     so no other page is affected
```

### 5. Prediction history & self-learning (follow-up)

`grade_price_forecasts()` (app/services/forecast/engine.py) fills in
`realized_price`/`error_pct`/`evaluated_at` on every `PriceForecastSnapshot`
row whose horizon has actually elapsed in stored history -- mirrors
`app.services.learning.engine.evaluate_predictions()`'s index-by-timestamp
join exactly (a forecast only becomes gradable once real history reaches
that far, never guessed). Runs as `grade_forecasts_job` on the existing
analysis cadence, right alongside `compute_forecast_job`.

Two new nullable columns on `price_forecast_snapshots` (migration 0027)
make this possible: `reference_timestamp` (the exact history candle the
forecast was computed from -- the join key) and `confidence_tier` (so the
history table can show Predicted/Actual/Error%/Confidence without
re-deriving it).

Self-learning: `price_forecast_quality_multiplier()` turns a symbol/
horizon's own measured average |error%| into a 0.0-1.0 discount, using
that forecast's own `expected_volatility_pct` (ATR as %-of-price) as the
"no better than noise" baseline -- a real already-computed number, not an
arbitrary constant, mirroring the Brier-vs-uninformative-baseline pattern
`ConvictionEngine` already uses for direction calibration. Surfaced as a
new `track_record` field on every forecast (`evaluated_count`,
`avg_abs_error_pct`, `quality_multiplier`, `adjusted_confidence_pct`),
kept deliberately separate from the existing `confidence` field (direction
calibration) since the two measure different things. `GET /api/forecast/
{symbol}/history` now also returns `accuracy_by_horizon`. The dashboard's
"Prediction History & Self-Learning" section shows the accuracy summary
per horizon plus the full graded history table.

### 6. Test results & verification

970 -> 1005 tests, all passing; `ruff check`/`format` clean (only the same
15 pre-existing, unrelated `UP042` findings untouched). Verified against a
real local Postgres + Redis with real synced BTC history (not mocks): all
four horizons returned distinct, real target prices/paths/distributions;
the dashboard hero card rendered correctly in a real browser (Playwright),
horizon tabs switched instantly without a full-page reload, and the "next
AI update" countdown ticked correctly. The follow-up grading loop was
verified against a real forecast row with its `reference_timestamp`
rewound to an already-stored earlier candle (simulating elapsed time
without waiting real days): `grade_forecasts_job` correctly found it,
computed a real error%, and persisted it, all visible end-to-end in the
dashboard's new history table and accuracy cards.

## Executive Market Summary

A second hero panel on the Overview page, directly below the AI Forecast
Center, answering "what should I know right now?" -- entirely out of numbers
other engines already compute (`app/services/executive_summary/engine.py`,
`GET /api/executive-summary/{symbol}`).

### 1. Reused, not rebuilt

- **Overall score, regime, risk, committee decision, consensus vote** are
  all read straight off the latest `WatchdogSnapshot` -- the same
  "never duplicate calculations already performed by Committee/Consensus/
  Scenario/Risk" reuse the Forecast Center already established -- rather
  than re-invoking the agent orchestrator, Committee, or GlobalScore from
  scratch.
- **Bullish/Bearish Factors** are assembled only from real, already-labeled
  signals: `TechnicalAnalysisSnapshot.active_signals` (the RSI/MACD/cross/
  trend events the technical engine already detected this cycle),
  Consensus's own bullish/bearish agent buckets plus each agent's own
  evidence excerpt, `ExplanationEngine`'s already-tagged supporting news,
  the real Crypto Fear & Greed classification, the ETF proxy's own
  classification (always labeled "proxy", never presented as confirmed
  flow data), and Whale Intelligence's own funding-rate reading. No factor
  is ever invented to fill out the list -- both sides render `[]` honestly
  when a source has nothing to say.
- **Market Health** (Liquidity/Volatility/Momentum/Sentiment/Institutional
  Activity/On-chain Activity/News Quality) reads real already-computed
  0-100 scores off `WatchdogSnapshot`, `GlobalMarketScore`,
  `TechnicalAnalysisSnapshot`, and `SentimentSnapshot`. On-chain Activity
  is honestly `null` today -- `OnChainIntelligenceEngine` is a documented
  no-data-source scaffold, exactly like the Forecast Center's Confidence
  Breakdown already shows it.

### 2. New composition (no new trading model)

- `classify_ai_action()` maps the AI Investment Committee's own decision
  (BUY/SELL/HOLD) and confidence, plus `GlobalScoreEngine`'s own
  `risk_score`, onto the requested 8-tier scale (Strong Buy/Buy/Accumulate/
  Hold/Reduce Risk/Take Profit/Sell/No Trade) -- pure presentation
  composition over 3 numbers this project already computes every cycle,
  always paired with a one-line reason citing the real inputs behind it.
- `compose_summary()` builds the 3-5 sentence narrative deterministically
  from the fields above -- the same string-composition style
  `ExplanationEngine`/`WatchdogEngine` already use elsewhere, never an LLM
  call (LLM report generation already has its own, separate, occasionally
  rate-limited path in this project; the Executive Summary never depends
  on it).

### 3. No new persistence

Every input here is already recomputed every analysis cycle by its own
engine/scheduler job (Watchdog's own cycle, GlobalScore, Sentiment,
Technical Analysis all run on the existing `analysis_interval_minutes`
cadence) -- re-reading them on each dashboard refresh satisfies "update
every analysis cycle" honestly, with no redundant new scheduler job and no
new migration.

### 4. Test results & verification

1005 -> 1028 tests, all passing; `ruff check`/`format` clean. Verified
against a real local Postgres + Redis: the endpoint was exercised against a
genuine `WatchdogSnapshot` row computed by a live scheduler cycle (real
Consensus/Committee/Sentiment/Technical Analysis data, not mocks), and the
dashboard panel was confirmed rendering correctly in a real browser
(Playwright) directly below the AI Forecast Center, with the Bullish/
Bearish Factors, Market Health bars, and AI Action badge all showing real,
distinct values.

## Why AI Thinks This

The "Why" dashboard page is now "Why AI Thinks This" -- a full per-engine
breakdown of the current prediction, so it's fully traceable back to the
real numbers behind it (`app/services/explainability/engine.py`, extends
`GET /api/explanation/{symbol}`).

### 1. Engine Breakdown -- Signal/Confidence/Weight/Explanation

For each of Technical Analysis, News, On-chain, Whales, Macro, Sentiment,
Correlations, and Historical Patterns, `ExplainabilityEngine.build()`
composes:

- **Signal** and **Weight** for Technical Analysis/News/Sentiment/Macro
  straight off the latest `WatchdogSnapshot.consensus` (the same
  persisted Consensus vote tally Forecast Center and Executive Summary
  already read) -- which bullish/bearish/neutral bucket the agent landed
  in, and its real % share of the vote weight. No re-invoking the agent
  orchestrator.
- **Confidence** reuses `ForecastEngine`'s own `_confidence_breakdown()`
  formulas, imported directly rather than re-implemented -- with one
  correction: Macro's confidence now reads `GlobalScoreEngine`'s own
  `macro_pressure_score` (a genuine macro-specific number) instead of the
  whole-market `WatchdogSnapshot.confidence_score` Forecast Center's row
  happens to reuse there.
- **On-chain** is honestly reported unavailable, with the real reason
  string (`OnChainIntelligenceEngine` is a documented no-data-source
  scaffold) -- never a fabricated score.
- **Whales/Correlations/Historical Patterns** have no dedicated Consensus
  agent vote, so Weight is honestly `None` for them. Their Signal/
  Explanation are composed from real fields instead: Whale Intelligence's
  own derivatives classification and funding rate; the real 30-day
  Pearson correlations from `CorrelationEngine`, strongest first;
  `ExplanationEngine`'s own historical analog matches, with a directional
  read derived honestly from the sign of their average forward return.

### 2. Final Prediction

A new `final_prediction` field anchors the page: the Consensus bullish/
bearish spread run through the same `classify_direction_label()` Forecast
Center already uses, plus the real Committee decision/recommendation from
`WatchdogSnapshot` -- so the page states the prediction once, then breaks
down every engine that fed it.

### 3. No duplicate logic, no new persistence

`ExplanationEngine.build()` is called once, unmodified, for the existing
evidence pack (still shown below the new breakdown); `engine_breakdown`
and `final_prediction` are added to that same dict, nothing is
recomputed. Every input is already-persisted data another engine's own
scheduler job computes every analysis cycle -- no new migration, no new
scheduler job.

### 4. Test results & verification

1028 -> 1041 tests, all passing; `ruff check`/`format` clean. Verified
against a real local Postgres + Redis: `/api/explanation/BTC` returned a
genuine 8-row breakdown computed from a live-scheduled `WatchdogSnapshot`
(real Consensus/Committee/Sentiment/Technical/Whale data), and the
dashboard page rendered correctly in a real browser (Playwright) with
Final Prediction and Engine Breakdown at the top, correctly colored by
signal, above the pre-existing supplementary sections.

## Prediction Accuracy

A new dashboard page tracks every price forecast permanently and shows how
accurate this project's own predictions really are -- Daily/Weekly/Monthly/
Asset accuracy, real trend charts, and confidence calibration -- entirely
built on the grading loop the Forecast Center follow-up already shipped
(`app/services/accuracy/engine.py`, `GET /api/accuracy`).

### 1. Two new graded fields, no new grading mechanism

`grade_price_forecasts()` (`app/services/forecast/engine.py`) already joins
every `PriceForecastSnapshot` against real elapsed history to fill in
`realized_price`/`error_pct`. This follow-up adds two more real, derived
fields to that same pass:

- **`direction_correct`** -- did the forecast's own directional call
  (Bullish/Bearish, from its own `direction` label) match the real sign of
  price change from `current_price` to `realized_price`? Honestly `None`
  for a "Neutral" call, since a neutral read makes no directional claim to
  grade.
- **`confidence_correct`** -- did the real `|error_pct|` stay within the
  forecast's own ATR-derived expected volatility band -- the exact same
  "no better than noise" baseline `price_forecast_quality_multiplier`
  already uses for its self-learning discount, recomputed here from the
  real ATR stored on the reference history candle. `None` until graded.

Migration `0028` adds both as nullable boolean columns -- no change to the
grading join itself, no new scheduler job.

### 2. Daily/Weekly/Monthly/Asset aggregation (new, pure functions)

`app/services/accuracy/engine.py` buckets every already-graded row by the
calendar day/ISO-week/month of its real `evaluated_at` timestamp, and
separately by symbol -- only periods/assets with at least one real graded
row ever appear, nothing is padded. Each bucket reports real evaluated
count, average absolute error%, direction accuracy%, and confidence
accuracy%. Since `PriceForecastSnapshot` grading is currently scheduled
BTC-only, "Asset Accuracy" today shows one row -- it generalizes honestly
the moment more symbols are graded, with no code change.

### 3. Dashboard

New "Prediction Accuracy" page: overall summary cards, two trend charts
(avg error%/direction accuracy% over daily buckets, reusing the existing
`svgLineChart()` primitive -- no new charting dependency), Daily/Weekly/
Monthly/Asset tables, and a Recent Graded Predictions table showing
Predicted/Actual/Error%/Direction/Confidence/Tier per row, colored
correct/wrong.

### 4. Test results & verification

1041 -> 1060 tests, all passing; `ruff check`/`format` clean. Verified the
full grading-to-dashboard path against a real local Postgres: computed a
genuine forecast, rewound its `reference_timestamp` to an earlier stored
candle with a real directional call, ran `grade_price_forecasts()`
directly, and confirmed it correctly graded a wrong directional call
(`direction_correct: false`, price moved against the stated Bullish call)
alongside a within-band error (`confidence_correct: true`) -- then
confirmed `/api/accuracy` aggregated it correctly and the new dashboard
page rendered it, in a real browser, with the right pass/fail coloring.

## Next-Generation AI Forecast Engine

Redesigns the AI Forecast Center's single price target into Bull/Base/Bear
scenario cases, a Prediction Range, Expected Max Drawdown/Momentum Score,
an 11-agent AI Consensus (up from 6), and a per-engine AI Explanation
breakdown -- all additive to the existing `GET /api/forecast/{symbol}`
payload, entirely reused from engines already built in this project. No
duplicate logic: every new number is either a new caller of an existing
pure function, or a small, honestly-derived composition following the same
patterns already established.

### 1. Bull / Base / Bear cases (new pure function, same math)

`compute_scenario_cases()` (`app/services/forecast/engine.py`) reuses the
exact normal approximation `compute_probability_distribution` already
builds (mean = `ProbabilityEngine`'s empirical `avg_forward_return_pct`,
std = ATR) -- not a second forecasting model:

- **Base Case** target = today's existing single `target_price`, unchanged.
- **Bull/Bear Case** targets = Base Case +-1 ATR (one volatility band away).
- **Probability** per case is `ProbabilityEngine`'s own real
  `prob_up_pct`/`prob_flat_pct`/`prob_down_pct` (already sums to 100) --
  not re-derived.
- **Confidence** per case scales the forecast's existing
  `effective_confidence_pct` proportionally to that case's probability
  relative to the dominant case, so the dominant case's confidence matches
  today's single forecast confidence exactly.

`compute_prediction_range()` reuses the same normal approximation's outer
+-1.5*ATR edges (already computed inside the probability distribution) to
expose an explicit Upper/Lower Bound.

### 2. Expected Max Drawdown & Momentum Score (new callers, no new formulas)

- `compute_expected_max_drawdown_pct()` feeds the symbol's real trailing
  30-day `return_pct` history straight into `compute_max_drawdown_pct()`
  (`app/services/backtest/metrics.py`) -- the same peak-to-trough drawdown
  Backtest/Portfolio already compute, applied to a new input.
- `compute_momentum_score()` feeds `TechnicalAnalysisSnapshot`'s own real
  signed momentum % into `center_scaled()` (`app/services/common/
  scoring.py`) -- the same "signed change -> 0-100 score centered at 50"
  primitive fear/greed/liquidity/macro_pressure already use.

### 3. AI Consensus expansion: 6 agents -> 11

`AgentOrchestrator` (`app/services/agents/orchestrator.py`) -- shared
app-wide by Watchdog, Committee, Consensus, Reports, Telegram, Replay, and
Shocks -- gains five new agents, each a real `AgentOutput` following the
existing agent pattern:

- **`WhaleAgent`** -- votes off `WhaleIntelligenceEngine`'s real
  derivatives classification (long_heavy/short_heavy/balanced); reports no
  direction when derivatives data is unavailable this cycle.
- **`PatternAgent`** -- votes off the last 10 real detected patterns from
  `PatternEngine`; since `PatternSignal` has no confidence field,
  confidence is a genuine recency-weighted agreement measure (more recent
  patterns count for more) rather than an invented number.
- **`RiskAgent`** -- votes off `GlobalScoreEngine`'s own `risk_score` (a
  distinct weighted blend from Macro's own risk_on/risk_off diff), reusing
  `direction_from_score()` inverted (higher risk = bearish for risk assets).
- **`OnchainAgent`** -- always reports no direction, honestly:
  `OnChainIntelligenceEngine` is a documented no-data-source scaffold.
  Contributes zero vote-weight change to any existing consumer until a real
  on-chain provider is wired in.
- **`CorrelationAgent`** -- also always reports no direction: no existing
  derivation turns `CorrelationEngine`'s real but unsigned pair correlations
  into a directional call for the reference symbol, and inventing one under
  time pressure was rejected in favor of honesty. Still surfaces the real
  correlation data in its evidence.

Only Whale/Pattern/Risk introduce new, real vote weight (deliberately
shifting Consensus/Committee percentages app-wide, as intended); On-chain/
Correlation are zero-behavior-change additions until real data exists.
Verified live against a real local Postgres: Watchdog, Committee, and
Consensus all correctly reflect the expanded 11-agent roster (`pattern`/
`onchain`/`correlation` honestly appear in `unavailable_agents` today since
no patterns/on-chain/correlation data exist yet in this environment).

### 4. AI Explanation (reused, not duplicated)

`GET /api/forecast/{symbol}` now also calls the existing `ExplainabilityEngine`
("Why AI Thinks This") at the API route layer -- not from `ForecastEngine`
itself, since `ExplainabilityEngine` already imports from `forecast.engine`
and a reverse import would create a cycle -- and merges its
`engine_breakdown` (Signal/Weight/Confidence/Reason per engine) and
`final_prediction` into the response under a new `ai_explanation` key. No
new computation: the exact same breakdown the "Why AI Thinks This" page
already shows.

### 5. Already shipped, no new work needed

Two items from this feature's spec were already fully built in prior work:
"Track prediction accuracy automatically" (the Prediction Accuracy
dashboard, `GET /api/accuracy`) and "What could invalidate this forecast"
(`ForecastEngine._what_can_change()`, already in the payload's
`what_can_change` field).

### 6. New/modified files

```
app/services/agents/whale_agent.py         -- new
app/services/agents/pattern_agent.py       -- new
app/services/agents/risk_agent.py          -- new
app/services/agents/onchain_agent.py       -- new
app/services/agents/correlation_agent.py   -- new
app/services/agents/orchestrator.py        -- +5 agents in __init__/run_all/
                                               build_agent_orchestrator
app/services/forecast/engine.py            -- compute_scenario_cases,
                                               compute_prediction_range,
                                               compute_expected_max_drawdown_pct,
                                               compute_momentum_score,
                                               _normal_mean_and_std (shared)
app/api/forecast.py                        -- merges ai_explanation into
                                               GET /api/forecast/{symbol}
app/static/dashboard/app.js                -- Bull/Base/Bear cards,
                                               Prediction Range/Max Drawdown/
                                               Momentum Score stats, AI
                                               Explanation table
tests/test_new_consensus_agents.py         -- new
tests/test_forecast_engine.py, test_forecast_api.py -- extended
```

### 7. Test results & verification

1073 -> 1083 tests, all passing; `ruff check`/`format` clean; dashboard
verified in a real browser (Playwright) against real local Postgres/Redis
data -- Bull/Base/Bear cards, Prediction Range, Expected Max Drawdown,
Momentum Score, the 11-agent AI Consensus grid, and the AI Explanation
table all rendered correctly, and horizon-tab switching (24h/3d/7d/30d)
correctly re-fetched and re-rendered every new section.

## Futures Simulator

A 100% demo/paper-trading futures terminal added inside this project's
existing architecture, built entirely on real market data with zero real
money, real Binance orders, withdrawals, or live trading anywhere in the
codebase -- no Binance API keys are ever accepted or stored. `GET
/api/simulator/*` (`app/api/futures_sim.py`) and `app/services/futures_sim/`
implement a full demo account/order/position/trade/ledger model: 10
symbols at 1x-75x leverage with SIMULATED per-symbol brackets, ISOLATED
and CROSS margin, ONE-WAY position mode, MARKET/LIMIT/STOP_MARKET/
TAKE_PROFIT_MARKET orders with a deterministic (no partial-fill) fill
model, a documented ISOLATED/CROSS liquidation engine, position-level
SL/TP, an EMA-smoothed SIMULATED MARK PRICE used for live PnL/equity
display (never for liquidation/trigger checks, which use the raw
reference price), real-data-when-available funding with an explicitly
labeled SIMULATED fallback, an immutable account ledger, Performance
Analytics (overall + by-side/symbol/leverage/strategy breakdowns, reusing
the existing backtest metrics engine), Risk Metrics (margin ratio,
distance to liquidation, concentration, daily loss) with permissive
HIGH_RISK/NEAR_LIQUIDATION/MARGIN_WARNING labels and optional per-account
Max Risk Settings overrides, and an optional Strategy Journal (per-trade
label/note/self-assessment tags) for Trade Review. The dashboard's
"Futures Simulator" nav item (`app/static/dashboard/app.js`,
`renderFuturesSimulator`) adds a 9-tab page (TRADE / POSITIONS / OPEN
ORDERS / ORDER HISTORY / TRADE HISTORY / PERFORMANCE / RISK / ACCOUNT
HISTORY / SETTINGS) built entirely from the existing dashboard primitives
-- no new frontend infrastructure. The TRADE tab shows the existing AI
Forecast Center's real forecast for the selected symbol and lets a user
optionally prefill SL/TP from it, but the AI forecast never opens a demo
position by itself -- every order is the result of an explicit user
click.

Every increment was live-verified against the real running
Postgres+Redis-backed server (curl and headless-Chromium Playwright
sessions) with real market data, never mocked-only. Full detail --
every formula (margin, PnL, fees, slippage, ROI, ISOLATED/CROSS
liquidation price derivations, mark price, funding), the complete API
surface, the dashboard's tab-by-tab behavior, and an honestly-scoped
"Known limitations" list (no candlestick/OHLC chart yet, no historical-
replay trading mode yet) -- lives in `docs/FUTURES_SIMULATOR.md` and
`docs/FUTURES_SIMULATOR_MATH.md`, kept current as a living document
across every increment rather than summarized once here.

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
- [`docs/FORECASTING_3_0.md`](docs/FORECASTING_3_0.md) -- closing report for the Forecasting 3.0 program (RMSE, the full 5-baseline challenge, CRPS, calibrated confidence, historical replay leakage validation): what already existed, what was missing, real coverage/win-rate/calibration numbers pulled live from a running instance, and honestly-scoped remaining limitations
- [`docs/FUTURES_SIMULATOR.md`](docs/FUTURES_SIMULATOR.md) -- 100% demo/paper-trading futures terminal (no real money, no real exchange orders): account/order/position model, ONE-WAY mode semantics, margin modes, liquidation/SL/TP monitoring, full API surface, and honestly-scoped remaining limitations; a living overview extended as each increment ships
- [`docs/FUTURES_SIMULATOR_MATH.md`](docs/FUTURES_SIMULATOR_MATH.md) -- every formula the Futures Simulator uses (margin, PnL, fees, slippage, ROI, ISOLATED and CROSS liquidation price with derivations, account equity, mark price, liquidation/SL/TP trigger logic), each mapped 1:1 to its unit-tested pure function

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
