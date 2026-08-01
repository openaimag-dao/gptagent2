import httpx
import pytest

from app.utils.http import default_retry


def _status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


async def test_default_retry_does_not_retry_on_429():
    attempts = 0

    @default_retry()
    async def call():
        nonlocal attempts
        attempts += 1
        raise _status_error(429)

    with pytest.raises(httpx.HTTPStatusError):
        await call()

    # A 429 means the provider's per-window quota is already exhausted --
    # retrying within this decorator's few-second backoff cannot possibly
    # help and only burns more of a free-tier budget that needs a full
    # window to refill, so it must fail fast on the first attempt.
    assert attempts == 1


async def test_default_retry_still_retries_on_server_errors():
    attempts = 0

    @default_retry()
    async def call():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise _status_error(502)
        return "ok"

    result = await call()

    assert result == "ok"
    assert attempts == 2


async def test_default_retry_still_retries_on_transport_errors():
    attempts = 0

    @default_retry()
    async def call():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise httpx.ConnectTimeout("timed out")
        return "ok"

    result = await call()

    assert result == "ok"
    assert attempts == 2
