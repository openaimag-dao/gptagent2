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

    # ---- Scheduling / networking ----
    market_data_interval_minutes: int = 5
    news_collection_interval_minutes: int = 10
    analysis_interval_minutes: int = 30
    report_interval_minutes: int = 30
    replay_interval_minutes: int = 15
    http_timeout_seconds: float = 15.0
