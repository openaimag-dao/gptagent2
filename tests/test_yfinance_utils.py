from unittest.mock import patch

from app.services.market.yfinance_utils import download_last_two_closes


async def test_accumulates_partial_results_across_attempts():
    """A ticker still missing after attempt 1 gets retried on attempt 2,
    even though other tickers in the same batch already succeeded --
    the bug this replaced would have dropped it permanently."""
    responses = [
        {"AAPL": (100.0, 99.0, 1000.0)},  # attempt 1: MSFT missing
        {"MSFT": (200.0, 198.0, 500.0)},  # attempt 2: MSFT recovers
    ]

    with (
        patch(
            "app.services.market.yfinance_utils.download_last_two_closes_sync",
            side_effect=responses,
        ),
        patch("asyncio.sleep"),
    ):
        result = await download_last_two_closes(["AAPL", "MSFT"], attempts=3)

    assert result == {
        "AAPL": (100.0, 99.0, 1000.0),
        "MSFT": (200.0, 198.0, 500.0),
    }


async def test_stops_early_once_everything_is_resolved():
    with patch(
        "app.services.market.yfinance_utils.download_last_two_closes_sync",
        side_effect=[{"AAPL": (100.0, 99.0, 1000.0)}],
    ) as mock_sync:
        result = await download_last_two_closes(["AAPL"], attempts=4)

    assert result == {"AAPL": (100.0, 99.0, 1000.0)}
    mock_sync.assert_called_once()


async def test_only_retries_still_missing_tickers():
    responses = [
        {"AAPL": (100.0, 99.0, 1000.0)},
        {},
    ]
    with (
        patch(
            "app.services.market.yfinance_utils.download_last_two_closes_sync",
            side_effect=responses,
        ) as mock_sync,
        patch("asyncio.sleep"),
    ):
        result = await download_last_two_closes(["AAPL", "MSFT"], attempts=2)

    assert result == {"AAPL": (100.0, 99.0, 1000.0)}
    # second call should only re-request the still-missing ticker
    mock_sync.assert_called_with(["MSFT"])


async def test_returns_whatever_accumulated_after_exhausting_attempts():
    with (
        patch(
            "app.services.market.yfinance_utils.download_last_two_closes_sync",
            return_value={},
        ),
        patch("asyncio.sleep"),
    ):
        result = await download_last_two_closes(["AAPL"], attempts=2)

    assert result == {}
