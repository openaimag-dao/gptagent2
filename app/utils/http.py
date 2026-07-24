import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


def build_http_client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": "ai-market-intelligence-bot/1.0"},
    )


def default_retry():
    """Retry preset for flaky upstream market-data APIs: 3 attempts, exponential backoff."""
    return retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
