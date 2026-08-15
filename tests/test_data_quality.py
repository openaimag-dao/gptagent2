from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.data_quality.engine import (
    DataQualityEngine,
    assess_symbol_quality,
    compute_data_quality_score,
)
from app.services.history.registry import HistorySymbolConfig
from app.services.history.schemas import Timeframe


def _row(timestamp: datetime) -> SimpleNamespace:
    return SimpleNamespace(timestamp=timestamp)


def test_assess_symbol_quality_empty_when_no_rows():
    result = assess_symbol_quality([], datetime(2026, 1, 10, tzinfo=UTC))
    assert result == {
        "status": "empty",
        "row_count": 0,
        "most_recent_timestamp": None,
        "days_since_last_update": None,
    }


def test_assess_symbol_quality_has_data_reports_row_count_and_freshness():
    rows = [_row(datetime(2026, 1, 1, tzinfo=UTC)), _row(datetime(2026, 1, 5, tzinfo=UTC))]
    result = assess_symbol_quality(rows, datetime(2026, 1, 10, tzinfo=UTC))
    assert result["status"] == "has_data"
    assert result["row_count"] == 2
    assert result["most_recent_timestamp"] == datetime(2026, 1, 5, tzinfo=UTC)
    assert result["days_since_last_update"] == 5


# ---- POST-V9 Phase 12: compute_data_quality_score ----


def test_compute_data_quality_score_zero_when_empty():
    assert compute_data_quality_score(None, "empty") == 0
    assert compute_data_quality_score(5, "empty") == 0


def test_compute_data_quality_score_zero_when_days_missing():
    assert compute_data_quality_score(None, "has_data") == 0


def test_compute_data_quality_score_full_when_fresh():
    assert compute_data_quality_score(0, "has_data") == 100
    assert compute_data_quality_score(1, "has_data") == 100


def test_compute_data_quality_score_zero_past_the_staleness_ceiling():
    assert compute_data_quality_score(30, "has_data") == 0
    assert compute_data_quality_score(365, "has_data") == 0


def test_compute_data_quality_score_is_monotonically_non_increasing_in_staleness():
    days = [0, 1, 5, 10, 15, 20, 25, 29, 30, 40]
    scores = [compute_data_quality_score(d, "has_data") for d in days]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] > scores[-1]


def test_assess_symbol_quality_never_labels_any_nonzero_row_count_as_stale():
    """No fabricated staleness threshold -- a symbol with data is always
    "has_data", however old, since different tables have very different
    natural update cadences (daily OHLCV vs. monthly FRED releases)."""
    rows = [_row(datetime(2020, 1, 1, tzinfo=UTC))]
    result = assess_symbol_quality(rows, datetime(2026, 1, 10, tzinfo=UTC))
    assert result["status"] == "has_data"
    assert result["days_since_last_update"] > 2000


def _config(
    symbol: str, timeframes: tuple[Timeframe, ...] = (Timeframe.DAILY,)
) -> HistorySymbolConfig:
    return HistorySymbolConfig(
        symbol=symbol, model=object, provider=AsyncMock(), timeframes=timeframes, market="crypto"
    )


async def test_assess_all_sweeps_full_registry_and_summarizes():
    registry = [_config("BTC"), _config("AAPL")]
    with (
        patch("app.services.data_quality.engine.build_registry", return_value=registry),
        patch(
            "app.services.data_quality.engine.get_series",
            new=AsyncMock(side_effect=[[_row(datetime(2026, 1, 1, tzinfo=UTC))], []]),
        ),
    ):
        engine = DataQualityEngine(AsyncMock())
        report = await engine.assess_all()

    assert report["summary"]["total"] == 2
    assert report["summary"]["has_data"] == 1
    assert report["summary"]["empty"] == 1
    assert report["summary"]["empty_symbols"] == ["AAPL"]
    btc_result = next(r for r in report["results"] if r["symbol"] == "BTC")
    aapl_result = next(r for r in report["results"] if r["symbol"] == "AAPL")
    assert btc_result["status"] == "has_data"
    assert aapl_result["status"] == "empty"


async def test_assess_all_covers_every_timeframe_a_symbol_declares():
    registry = [_config("BTC", timeframes=(Timeframe.DAILY, Timeframe.FOUR_HOUR))]
    with (
        patch("app.services.data_quality.engine.build_registry", return_value=registry),
        patch("app.services.data_quality.engine.get_series", new=AsyncMock(return_value=[])),
    ):
        engine = DataQualityEngine(AsyncMock())
        report = await engine.assess_all()

    assert report["summary"]["total"] == 2
    assert {r["timeframe"] for r in report["results"]} == {"1d", "4h"}


async def test_assess_all_empty_registry_reports_zero_totals():
    with patch("app.services.data_quality.engine.build_registry", return_value=[]):
        engine = DataQualityEngine(AsyncMock())
        report = await engine.assess_all()

    assert report["summary"] == {
        "total": 0,
        "empty": 0,
        "has_data": 0,
        "empty_symbols": [],
    }
