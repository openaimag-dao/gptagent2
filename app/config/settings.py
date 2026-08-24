from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration, populated from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- App ----
    app_env: str = "development"
    log_level: str = "INFO"
    # Required to call POST /api/admin/* (sync-history, migrate) -- those
    # endpoints run alembic migrations and trigger multi-year external data
    # backfills, so they must never be reachable by an unauthenticated
    # caller on a public deployment. None means "not configured", which
    # app/api/admin.py treats as "reject every request" rather than "allow
    # every request" -- see require_admin_key() there.
    admin_api_key: str | None = None

    # ---- Infrastructure (sensible local/docker-compose defaults) ----
    database_url: str = "postgresql+asyncpg://market_intel:market_intel@localhost:5432/market_intel"
    redis_url: str = "redis://localhost:6379/0"

    @field_validator("database_url")
    @classmethod
    def _ensure_asyncpg_driver(cls, value: str) -> str:
        """Normalizes bare postgres(ql):// URLs (e.g. Railway's DATABASE_URL) to
        use the asyncpg driver our engine requires, so pointing DATABASE_URL at
        a hosting platform's own connection string just works without having
        to manually reassemble it with a "+asyncpg" suffix."""
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value[len(prefix) :]
        return value

    # ---- Telegram ----
    telegram_bot_token: str | None = None
    # Comma-separated chat IDs automatic reports are broadcast to, e.g. "123456789,-100987654321"
    telegram_broadcast_chat_ids: str | None = None

    # ---- LLM (Google Gemini, optional) ----
    # Preferred provider when configured -- Gemini has a genuine ongoing
    # free tier (unlike Anthropic/OpenAI/xAI below, which are pay-per-token
    # with only a one-time trial credit). Falls back to Anthropic, then
    # OpenAI, then xAI, in that order, when unconfigured or its call fails.
    # See app/llm/client.py. Model defaults to the "-latest" alias rather
    # than a pinned version -- pinned Gemini model names get deprecated for
    # new API keys/projects without warning (observed live: gemini-2.5-flash
    # returned 404 "no longer available to new users" while still listed by
    # the models endpoint).
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-flash-latest"

    # ---- LLM (Anthropic Claude, optional) ----
    # Second choice, tried when Gemini is unconfigured or fails. Falls back
    # to the OpenAI-compatible client below on its own failure.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5-20250929"

    # ---- LLM (OpenAI-compatible) ----
    # Third choice, tried when Gemini/Anthropic are both unconfigured or
    # fail. Falls back to xAI below on its own failure.
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # ---- LLM (xAI Grok, optional) ----
    # Last-resort fallback, or the only provider if Gemini/Anthropic/OpenAI
    # are all unconfigured. xAI's API is OpenAI-compatible, so this reuses
    # the same transport as the OpenAI client above with a different
    # base URL/model.
    xai_api_key: str | None = None
    xai_base_url: str = "https://api.x.ai/v1"
    xai_model: str = "grok-4.5"

    # ---- Crypto data (CoinGecko) ----
    coingecko_api_key: str | None = None
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"

    # ---- Macro data (FRED) ----
    fred_api_key: str | None = None

    # ---- Indices/stocks fallback chain (optional) ----
    # Primary: Twelve Data (free tier: 800 credits/day, ~4h delay on some
    # plans). Fallback: Alpha Vantage (free tier: 5 requests/min, daily-only).
    # Both are optional -- unset means that link of the chain is skipped and
    # the next one (down to the existing yfinance path, then honest
    # "not available") is tried instead. See app/services/market/multisource_*.
    twelvedata_api_key: str | None = None
    alphavantage_api_key: str | None = None

    # ---- Whale/on-chain derivatives data (optional) ----
    # Primary: CoinGlass. Fallback: CoinGecko's keyless `/derivatives`
    # endpoint (no separate key needed -- reuses coingecko_api_key/
    # coingecko_base_url above, or works unauthenticated). Both cover
    # derivatives-market aggregates only (funding rate, open interest --
    # CoinGlass adds liquidations and long/short ratio) -- neither is an
    # on-chain wallet tracker, so exchange netflow / large-wallet-change /
    # stablecoin-supply-change stay honestly unavailable even with these
    # configured. See app/services/whales/engine.py.
    coinglass_api_key: str | None = None

    # ---- On-chain intelligence (optional, v4.0) ----
    # No provider is wired in yet -- OnChainIntelligenceEngine honestly
    # reports exchange netflow/reserves, SOPR, MVRV, NUPL, dormancy, coin
    # days destroyed, active/new addresses, TVL, stablecoin supply and
    # large transfers as unavailable regardless of these being set, until a
    # client for one of these is implemented. Glassnode covers general
    # on-chain metrics; Helius is a Solana-native indexer for
    # Solana-specific whale wallet activity / DEX volume / bridge activity.
    # See app/services/onchain/engine.py.
    glassnode_api_key: str | None = None
    helius_api_key: str | None = None

    # ---- TradingView MCP: Institutional Technical Analysis Provider (optional, v5.3) ----
    # No MCP server is configured by default -- TechnicalAnalysisProvider
    # falls back to indicators computed locally from this project's own
    # synced OHLCV history (1h/4h/1d only; see app/services/technical/
    # provider.py for exactly which symbols/timeframes that covers). Set
    # both to point at a real TradingView MCP endpoint to prefer it.
    tradingview_mcp_url: str | None = None
    tradingview_mcp_api_key: str | None = None

    # ---- Scheduling / networking ----
    market_data_interval_minutes: int = 5
    news_collection_interval_minutes: int = 10
    analysis_interval_minutes: int = 30
    report_interval_minutes: int = 30
    replay_interval_minutes: int = 15
    # v5.5 Market Scanner: 15 minutes, not market_data_interval_minutes's 5 --
    # the scanner tracks up to ~500 symbols per cycle (2 paginated CoinGecko
    # /coins/markets calls), so a 5-minute cadence would multiply API calls
    # and stored ScannerSnapshot rows 3x for a window granularity nothing else
    # in this project needs. 1m/5m windows are honestly not offered for the
    # scanner's universe -- see app/services/scanner/engine.py.
    scanner_interval_minutes: int = 15
    scanner_universe_refresh_hours: int = 24
    http_timeout_seconds: float = 15.0
    # Root cause of the "AI Forecast Center shows a wildly stale target
    # price" bug: ForecastEngine/ProbabilityEngine compute a forecast's
    # current_price/ATR basis from CryptoHistory's DAILY rows
    # (app/services/forecast/engine.py's compute()), but until this
    # setting's job existed nothing ever refreshed that table
    # automatically -- history sync only ran on a manual admin trigger.
    # 60 minutes: HistorySyncEngine.sync_symbol_timeframe is incremental
    # (only asks the provider for candles after the latest stored
    # timestamp, see its own docstring), so this is cheap to run this
    # often; scoped to crypto+DAILY only (5 symbols, 1 CoinGecko call
    # each) -- NOT the full ~25-symbol/4-provider registry, which stays
    # manual-trigger-only so this fix doesn't add load to yfinance
    # (already unreliable from this deployment's egress IP) or other
    # providers this bug has nothing to do with.
    crypto_history_sync_interval_minutes: int = 60

    # ---- Forecast / Prediction Quality (V9) ----
    # Width in percentage points of each Prediction Quality Lab calibration
    # bucket (app/services/quality/metrics.py compute_calibration) -- 10
    # gives a finer-grained "is 70% confidence actually right 70% of the
    # time" curve than the previous fixed 20pp bins, at the cost of thinner
    # per-bucket sample sizes. Config-driven so this can be tuned without a
    # code change as more graded predictions accumulate.
    calibration_bin_width_pct: int = 10

    # ---- Alert config (V9) ----
    # Per-category cooldown in minutes, read via
    # app.services.shocks.detectors.resolve_cooldown_minutes(). A category
    # left out of this dict keeps this project's original hardcoded
    # default (120 min for Scanner/CriticalAlertEngine episode staleness,
    # 60 min for AlertEngine's own re-broadcast gate) -- these were
    # previously the ONLY value every category shared, now per-category
    # and tunable without a code change. "critical" is a distinct override
    # applied on top of a detection's own category cooldown whenever its
    # gated tier is "critical" -- 0 minutes means a critical-tier episode
    # is never treated as "already notified, suppress" the way lower
    # tiers are.
    alert_cooldown_minutes: dict[str, int] = {
        "price_event": 15,
        "price_shock": 15,
        "volume_spike": 20,
        "breakout": 30,
        "regime_change": 60,
        "forecast_change": 30,
        "multi_asset_shock": 30,
        "crypto_market_shock": 30,
        "sector_ecosystem": 30,
        "critical": 0,
    }
    # Bounds on the realized-volatility ratio multiplier applied to
    # app.services.scanner.detectors.price_ladder_for()'s DEFAULT_PRICE_LADDER
    # -- a 3% move means something very different for BTC (typically ~1-2%
    # daily volatility) than for a small-cap swinging 15%/day, so the
    # ladder scales with how volatile a symbol has actually been recently
    # rather than staying a flat absolute percentage for every symbol.
    volatility_ladder_min_multiplier: float = 0.5
    volatility_ladder_max_multiplier: float = 2.5

    # ---- Agent reliability weighting (V9 Increment 8) ----
    # AgentReliabilityEngine's per-agent accuracy is a Bayesian shrinkage
    # estimate toward an uninformative 50% prior, weighted by this many
    # pseudo-observations -- a brand-new agent with 1-2 evaluated calls sits
    # close to 50% (its raw accuracy is too noisy to trust yet); an agent
    # with a long track record is barely pulled off its raw accuracy at
    # all. Higher = more conservative (needs more evaluated calls before
    # its own accuracy is trusted).
    reliability_shrinkage_pseudo_count: int = 10
    # Half-life in days for recency-weighting each evaluated prediction
    # before it's folded into an agent's accuracy -- a call from
    # half_life_days ago counts for half as much as one made today, so
    # reliability tracks an agent's CURRENT edge rather than its all-time
    # average (a regime shift that broke a previously-good agent shows up
    # within roughly one half-life instead of being diluted forever).
    reliability_recency_half_life_days: float = 30.0
    # POST-V9 Phase 5: AgentReliabilityEngine.evaluate_reliability_hierarchical
    # falls back from a narrow (horizon, regime) slice to a broader one
    # whenever the narrow slice's recency-weighted effective sample size is
    # below this threshold -- e.g. 2 stale predictions in "bull" regime
    # should not be treated as a reliable regime-specific accuracy estimate;
    # it should fall back to the agent's horizon-level or global accuracy
    # instead. Effective sample size is in decayed-observation units, not
    # raw row counts, so a small number of very recent predictions can still
    # clear this bar.
    reliability_hierarchical_min_effective_sample: float = 5.0

    # ---- Agent vote correlation / redundancy (POST-V9 Phase 6) ----
    # How many of an agent-pair's most recent SHARED reference_timestamps
    # (both agents logged a direction) to correlate -- a rolling bounded
    # window, not a full pairwise matrix over all stored history, so the
    # cost of evaluate_agent_correlations() stays bounded as prediction
    # logs accumulate.
    agent_correlation_window: int = 30
    # Below this many shared observations, a pair's correlation is honestly
    # reported as unavailable (None) rather than a noisy small-sample guess.
    agent_correlation_min_sample_size: int = 5
    # Upper bound (percentage points) on how much of an agent's consensus
    # weight a perfectly-correlated (redundant) partner can discount --
    # mirrors reliability_shrinkage_pseudo_count's role of keeping any
    # single adjustment bounded rather than able to zero out an agent.
    agent_correlation_max_redundancy_penalty_pct: float = 30.0

    # ---- Adaptive consensus weight bound (POST-V9 Phase 7) ----
    # Caps any single agent's share of total cast consensus weight, even
    # after reliability/redundancy scaling is applied at maximum -- so one
    # highly-confident, highly-reliable, uncorrelated agent can never
    # single-handedly determine the consensus direction. Only takes effect
    # when at least 2 agents report a direction this cycle (a lone
    # reporting agent's 100% share isn't "dominance" -- there is nothing
    # else to weigh it against).
    consensus_max_agent_weight_pct: float = 60.0

    # ---- Trade Setup historical expectancy backtest (POST-V9 Phase 9) ----
    # How many forward daily bars the walk-forward simulator searches for a
    # stop/target touch before calling a hypothetical trade "open" (neither
    # hit within the window) -- independent of the forecast horizon itself,
    # since a 2:1 R:R stop/target can take longer to resolve than the
    # horizon the forecast call was made for.
    trade_setup_backtest_max_holding_days: int = 30
    # Below this many backtested (non-"open") trade instances, expectancy
    # stats are honestly reported as "insufficient" rather than implying a
    # validated edge off a handful of historical trades.
    trade_setup_backtest_min_sample_size: int = 30
    trade_setup_backtest_reliable_sample_size: int = 100

    # ---- Alert performance analytics (V9 Increment 9) ----
    # How many days after an alert fires to look up its symbol's forward
    # price change -- an alert is only gradable once real synced history
    # reaches this far past `triggered_at` (never guessed early).
    alert_grading_horizon_days: int = 3
    # Minimum |realized_move_pct| over that horizon to count as a
    # "significant" (non-noise) move -- the one hit-rate every gradable
    # alert type gets, independent of whether the alert made a directional
    # claim.
    alert_grading_significant_move_pct: float = 3.0

    # ---- POST-V9 Phase 3: calibration statistical honesty ----
    # A calibration bucket (app.services.quality.metrics.compute_calibration)
    # below this many graded predictions is labeled "insufficient" --
    # displayed, never hidden, but flagged so it isn't read as strong
    # statistical evidence. At or above `calibration_reliable_sample_size`
    # it's labeled "reliable"; between the two, "usable".
    calibration_min_sample_size: int = 30
    calibration_reliable_sample_size: int = 100

    # ---- Live Dashboard Upgrade: realtime price stream ----
    # Coinbase Exchange's public market-data WebSocket needs no API key and
    # has no meaningful rate limit for a handful of ticker streams --
    # unlike CoinGecko (the sole REST price source, see aggregator.py),
    # which is already shared with the 500-symbol Scanner's free-tier
    # quota. Originally built against Binance's combined-stream WebSocket,
    # but Binance.com geo-blocks datacenter/cloud-hosting IP ranges as a
    # matter of regulatory policy -- this surfaced as a permanently
    # OFFLINE feed on this project's actual Railway deployment. Coinbase
    # is a US-licensed exchange with no comparable reason to block
    # US-origin/cloud traffic.
    realtime_enabled: bool = True
    # Futures Simulator (Phase 4): extended to the simulator's full
    # 10-symbol supported-asset list (was missing DOGE/AVAX/SUI) --
    # to_coinbase_product() builds "{SYMBOL}-USD" generically, and Coinbase
    # lists all three, so this is a watchlist entry, not new client code.
    realtime_watchlist: str = "BTC,ETH,SOL,BNB,XRP,DOGE,LINK,AVAX,SUI,UNI"
    realtime_ws_url: str = "wss://ws-feed.exchange.coinbase.com"
    # Comma-separated seconds; reconnect attempts walk this list and hold
    # at the last value rather than growing unbounded or tight-looping.
    realtime_reconnect_backoff_seconds: str = "1,2,5,10,30"
    # Freshness bands for a realtime tick's age (seconds). Below `live` is
    # "live", [live, recent) is "recent", [recent, delayed) is "delayed",
    # [delayed, stale) is "stale", >= stale is "offline" -- see
    # app.services.realtime.freshness.classify_freshness().
    realtime_freshness_live_seconds: float = 5.0
    realtime_freshness_recent_seconds: float = 30.0
    realtime_freshness_delayed_seconds: float = 120.0
    realtime_freshness_stale_seconds: float = 300.0

    # ---- Forecasting 2.0: official daily forecast (Part 1-4) ----
    # Comma-separated, parsed with the same app.services.realtime.config.
    # parse_watchlist() the realtime watchlist already uses. Exactly one
    # official 24h forecast per symbol per UTC calendar day is generated
    # for this roster -- distinct from the existing compute_forecast_job's
    # intraday recomputes, which keep running for every symbol they
    # already cover. LINK/UNI need app.services.history.registry's crypto
    # history synced before a forecast is possible for them (see that
    # registry's own docstring) -- until then compute() honestly returns
    # None ("insufficient data") for those two, same as any other symbol
    # without enough history, never a fabricated result.
    official_forecast_symbols: str = "BTC,SOL,LINK,UNI"
    # UTC hour (0-23) the daily job fires at -- configurable rather than
    # hardcoded, per this feature's own honesty requirement that forecast
    # timing be an explicit, auditable setting.
    daily_forecast_hour_utc: int = 0
    # Freshness bands for an official daily forecast's age (seconds), fed
    # into the same app.services.realtime.freshness.classify_freshness()
    # the realtime price path uses (app/api/forecast.py's
    # _with_official_freshness) -- reused, not duplicated. A completely
    # different scale from realtime_freshness_* above: a forecast that's
    # meant to stay valid for a full UTC day is not "stale" the way a
    # 30-second-old price tick would be. Root cause of the "24H Forecast
    # looks stale" report this fixes: the official daily forecast card
    # showed no computed-at/freshness signal at all, so a working
    # once-per-day design (see is_official_daily's own docstring) looked
    # indistinguishable from a broken/frozen one.
    official_forecast_freshness_live_seconds: float = 3600.0  # 1h
    official_forecast_freshness_recent_seconds: float = 21600.0  # 6h
    official_forecast_freshness_delayed_seconds: float = 72000.0  # 20h
    # 26h -- slack past the 24h day boundary
    official_forecast_freshness_stale_seconds: float = 93600.0
    # Below this many graded observations, Agent Performance reports
    # "insufficient sample" instead of a percentage -- official daily
    # forecasts accumulate at most one per symbol per day, so this is
    # deliberately smaller than calibration_min_sample_size (30) above,
    # which grades against the much higher-volume intraday path.
    agent_performance_min_sample_size: int = 10
    # Learning Center (Part 33/Page 7): a regime-vs-regime accuracy
    # comparison for one (agent, symbol) is only ever stated as "what the
    # system learned" when BOTH regime buckets independently clear this
    # sample size -- smaller than agent_performance_min_sample_size since
    # splitting by regime on top of (agent, symbol) shrinks each bucket
    # further, but still a real floor, never zero. min_gap_pct is the
    # minimum accuracy-percentage-point difference between the two
    # regimes before it's worth surfacing at all -- filters out noise
    # from two buckets that are statistically indistinguishable.
    learning_insight_min_sample_size: int = 5

    # ---- Futures Simulator: demo/paper-trading terminal ----
    # Everything below configures a fully virtual futures account -- no
    # real money, no real exchange orders, no Binance API keys anywhere in
    # this codebase. Real market data (price/candles) drives execution;
    # only the account/position/order/fee/funding/liquidation state is
    # simulated. See docs/FUTURES_SIMULATOR.md and
    # docs/FUTURES_SIMULATOR_MATH.md for the full model.
    futures_sim_symbols: str = "BTC,ETH,SOL,BNB,XRP,DOGE,LINK,AVAX,SUI,UNI"
    futures_sim_initial_balance_usd: float = 10000.0
    # Binance USDT-M's own default (non-VIP) schedule -- used only as a
    # realistic starting point for the simulated fee schedule, not fetched
    # live from any exchange.
    futures_sim_maker_fee_pct: float = 0.02
    futures_sim_taker_fee_pct: float = 0.04
    # Applied to every simulated MARKET order fill (both directions) --
    # never zero, since a real market order always crosses some spread.
    futures_sim_market_slippage_pct: float = 0.02
    futures_sim_leverage_options: str = "1,2,3,5,10,15,20,25,30,50,75"
    # Per-symbol leverage/maintenance-margin brackets are SIMULATED (see
    # FUTURES_LEVERAGE_BRACKETS in app.services.futures_sim.engine) --
    # this is the fallback used only if a symbol is somehow missing from
    # that table, kept deliberately conservative.
    futures_sim_default_max_leverage: int = 20
    futures_sim_default_maintenance_margin_pct: float = 1.0
    # How often the scheduler scans every OPEN position for liquidation /
    # stop-loss / take-profit triggers, and every resting LIMIT/STOP_MARKET
    # /TAKE_PROFIT_MARKET order for a crossed trigger price (task: both can
    # happen purely from a price move, with no further action from the
    # user). Shared by both jobs since they're the same "how fresh does
    # simulator state need to be" cadence. Kept tight since a demo
    # simulator has no real exchange-side engine watching prices live.
    futures_sim_position_monitor_interval_minutes: float = 1.0
    # Real exchanges settle funding every 8 hours -- matched here so the
    # simulator's funding cadence "feels" like the real thing rather than
    # an arbitrary interval.
    futures_sim_funding_interval_hours: float = 8.0
    # Used ONLY when a symbol's real funding rate is unavailable (no
    # CoinGlass/CoinGecko derivatives data) -- explicitly labeled
    # SIMULATED wherever charged (task: never present a simulated number
    # as real). A small, realistic-magnitude fraction, not zero (funding
    # is rarely exactly 0 on a real exchange) and not fabricated per-symbol
    # variation.
    futures_sim_simulated_funding_rate_pct: float = 0.01
    # Smoothing factor for the SIMULATED MARK PRICE EMA (task: mark price
    # must not always be just the last traded price) -- higher tracks the
    # real reference price more closely, lower smooths harder. 0.3 is a
    # standard EMA smoothing choice, not tuned against any real exchange's
    # own mark-price formula (this project has no real index-price feed to
    # match against).
    futures_sim_mark_price_ema_alpha: float = 0.3
    learning_insight_min_gap_pct: float = 15.0
