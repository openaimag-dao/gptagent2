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
                return "postgresql+asyncpg://" + value[len(prefix):]
        return value

    # ---- Telegram ----
    telegram_bot_token: str | None = None
    # Comma-separated chat IDs automatic reports are broadcast to, e.g. "123456789,-100987654321"
    telegram_broadcast_chat_ids: str | None = None

    # ---- LLM (OpenAI-compatible) ----
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # ---- Crypto data (CoinGecko) ----
    coingecko_api_key: str | None = None
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"

    # ---- Macro data (FRED) ----
    fred_api_key: str | None = None

    # ---- Whale/on-chain data (optional; no provider implemented yet) ----
    whale_api_key: str | None = None

    # ---- Scheduling / networking ----
    market_data_interval_minutes: int = 5
    news_collection_interval_minutes: int = 10
    analysis_interval_minutes: int = 30
    report_interval_minutes: int = 30
    http_timeout_seconds: float = 15.0
