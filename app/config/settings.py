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

    # ---- Telegram ----
    telegram_bot_token: str | None = None

    # ---- LLM (OpenAI-compatible) ----
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # ---- Crypto data (CoinGecko) ----
    coingecko_api_key: str | None = None
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"

    # ---- Macro data (FRED) ----
    fred_api_key: str | None = None

    # ---- Scheduling / networking ----
    market_data_interval_minutes: int = 5
    news_collection_interval_minutes: int = 10
    analysis_interval_minutes: int = 30
    report_interval_minutes: int = 30
    http_timeout_seconds: float = 15.0
