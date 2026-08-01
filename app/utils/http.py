import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


def build_http_client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": "ai-market-intelligence-bot/1.0"},
    )


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        # A 429 means the provider's rate/credit budget for this window is
        # already exhausted -- retrying within the next few seconds (this
        # decorator's backoff tops out at 10s) cannot possibly succeed and
        # only burns more of a free-tier quota that needs a full window to
        # refill. Every other HTTP error (5xx, etc.) is still worth retrying.
        return exc.response.status_code != 429
    return isinstance(exc, httpx.TransportError)


def default_retry():
    """Retry preset for flaky upstream market-data APIs: 3 attempts, exponential backoff."""
    return retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
    )
