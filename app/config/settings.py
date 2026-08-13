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
