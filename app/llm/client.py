from openai import AsyncOpenAI

from app.config import get_settings

_client: AsyncOpenAI | None = None


def get_llm_client() -> AsyncOpenAI:
    """Returns a cached AsyncOpenAI client pointed at the configured (OpenAI-compatible) endpoint.

    Raises a clear error if no key is configured, rather than silently
    returning a client that will fail on first use.
    """
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not configured; AI analysis/report generation is unavailable"
            )
        _client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    return _client
