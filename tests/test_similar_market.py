from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.analysis.regime import MarketRegime, reconstruct_regime_at
from app.services.history.schemas import Timeframe
from app.services.similar_market.engine import (
    SimilarMarketEngine,
    build_historical_lesson,
)

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _row(return_pct: float | None, close: float = 100.0):
    return SimpleNamespace(return_pct=return_pct, close=close)


def test_reconstructs_risk_on_when_all_signals_agree():
    regime_index = {
        "SPX": {_TS: _row(0.01)},
        "BTC": {_TS: _row(0.02)},
        "VIX": {_TS: _row(-0.05)},
        "DXY": {_TS: _row(-0.01)},
        "GOLD": {_TS: _row(0.0)},
        "US10Y": {_TS: _row(0.0)},
        "FEDRATE": {_TS: _row(0.0)},
    }
    assert reconstruct_regime_at(regime_index, _TS) == MarketRegime.RISK_ON


def test_returns_none_below_minimum_symbol_count():
    regime_index = {
        "SPX": {_TS: _row(0.01)},
        "BTC": {_TS: _row(0.02)},
        # everything else missing this timestamp
        "VIX": {},
        "DXY": {},
        "GOLD": {},
        "US10Y": {},
        "FEDRATE": {},
    }
    assert reconstruct_regime_at(regime_index, _TS) is None


def test_missing_return_pct_excludes_that_symbol():
    regime_index = {
        "SPX": {_TS: _row(0.01)},
        "BTC": {_TS: _row(0.02)},
        "VIX": {_TS: _row(-0.05)},
        "DXY": {_TS: _row(None)},  # present but no usable value
        "GOLD": {},
        "US10Y": {},
        "FEDRATE": {},
    }
    # Only 3 usable symbols (DXY excluded) -> below the 4-symbol minimum.
    assert reconstruct_regime_at(regime_index, _TS) is None


def test_returns_neutral_when_signals_disagree():
    regime_index = {
        "SPX": {_TS: _row(0.01)},
        "BTC": {_TS: _row(-0.02)},
        "VIX": {_TS: _row(0.03)},
        "DXY": {_TS: _row(0.01)},
        "GOLD": {},
        "US10Y": {},
        "FEDRATE": {},
    }
    assert reconstruct_regime_at(regime_index, _TS) == MarketRegime.NEUTRAL


def _match(similarity: float, regime: str | None, **forward_returns_pct: float | None) -> dict:
    return {
        "date": _TS,
        "similarity": similarity,
        "market_regime": regime,
        "rsi": 50.0,
        "volatility": 1.0,
        "btc_result_pct": None,
        "nasdaq_result_pct": None,
        "forward_returns_pct": {
            "1d": forward_returns_pct.get("d1"),
            "3d": forward_returns_pct.get("d3"),
            "7d": forward_returns_pct.get("d7"),
            "30d": forward_returns_pct.get("d30"),
        },
    }


def test_build_historical_lesson_returns_none_with_no_matches():
    assert build_historical_lesson("BTC", []) is None


def test_build_historical_lesson_returns_none_when_primary_horizon_unavailable():
    matches = [_match(80.0, "risk_on", d1=1.0, d3=2.0, d7=None, d30=None)]
    assert build_historical_lesson("BTC", matches) is None


def test_build_historical_lesson_composes_from_forward_returns():
    matches = [
        _match(80.0, "risk_on", d1=1.0, d3=2.0, d7=3.0, d30=-5.0),
        _match(90.0, "risk_on", d1=1.0, d3=2.0, d7=3.0, d30=-5.0),
        _match(70.0, "risk_off", d1=-1.0, d3=-2.0, d7=-3.0, d30=5.0),
    ]

    lesson = build_historical_lesson("BTC", matches)

    assert lesson["symbol"] == "BTC"
    assert lesson["occurrences"] == 3
    assert lesson["horizon_days"] == 7
    assert lesson["how_similar_pct"] == 80.0  # avg(80, 90, 70)
    assert lesson["average_outcome_pct"] == 1.0  # avg(3.0, 3.0, -3.0)
    assert lesson["probability_pct"] == 66.67  # 2 of 3 matches moved up
    assert lesson["dominant_regime"] == "risk_on"
    assert "2/3" not in lesson["typical_duration"]  # a plain-language sentence, not raw fractions
    assert "at least 7 day" in lesson["typical_duration"]
    assert "BTC" in lesson["what_happened"]
    assert "risk on" in lesson["what_happened"]
    assert "66.67% historical win rate" in lesson["main_lesson"]
    # p10..p90 of the same 7d forward returns (3.0, 3.0, -3.0 in %, i.e.
    # 0.03/0.03/-0.03 as fractions) that average_outcome_pct/probability_pct
    # were computed from -- the spread, not a second dataset. Two of the
    # three values tie at 3.0, so p50 and p90 also tie; only p10 (pulled
    # down by the lone -3.0) is guaranteed to differ.
    distribution = lesson["outcome_distribution_pct"]
    assert distribution is not None
    assert distribution["p10_pct"] < distribution["p90_pct"]
    assert distribution["p50_pct"] == distribution["p90_pct"] == 3.0


def test_build_historical_lesson_reports_no_persistence_when_direction_flips_immediately():
    matches = [
        _match(80.0, "risk_on", d1=-1.0, d3=2.0, d7=3.0, d30=4.0),
        _match(90.0, "risk_on", d1=-1.0, d3=2.0, d7=3.0, d30=4.0),
        _match(70.0, "risk_off", d1=1.0, d3=-2.0, d7=-3.0, d30=-4.0),
    ]

    lesson = build_historical_lesson("BTC", matches)

    # 7d direction is "up" (avg +1.0%), but the 1d horizon has only a 1/3
    # win rate for "up" -- persistence breaks immediately.
    assert (
        lesson["typical_duration"]
        == "No consistent persistence pattern across the tested horizons."
    )


def _history_rows(n: int, base: datetime = datetime(2020, 1, 1, tzinfo=UTC)) -> list:
    # Row 0 is engineered to be the closest RSI match to the "current"
    # (last) row -- everything in between is far away so find_similar_
    # episodes() picks row 0 unambiguously with k=1.
    rows = []
    for i in range(n):
        rsi = 30.0 if i == 0 else (32.0 if i == n - 1 else 80.0)
        rows.append(
            SimpleNamespace(
                timestamp=base + timedelta(days=i), rsi=rsi, volatility=None, return_pct=0.01
            )
        )
    return rows


def _empty_regime_index() -> dict:
    return {"BTC": {}, "SPX": {}, "VIX": {}, "DXY": {}, "GOLD": {}, "US10Y": {}, "FEDRATE": {}}


def _event_session_factory(events: list):
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=events)
    session.__aenter__.return_value = session
    return MagicMock(return_value=session), session


async def test_find_similar_periods_omits_nearby_events_and_skips_the_query_by_default():
    session_factory, session = _event_session_factory([])
    engine = SimilarMarketEngine(session_factory)

    with (
        patch(
            "app.services.similar_market.engine.get_series",
            AsyncMock(return_value=_history_rows(32)),
        ),
        patch(
            "app.services.similar_market.engine.build_regime_index",
            AsyncMock(return_value=_empty_regime_index()),
        ),
    ):
        matches = await engine.find_similar_periods("ETH", object, Timeframe.DAILY, k=1)

    assert len(matches) == 1
    assert "nearby_events" not in matches[0]
    session.scalars.assert_not_awaited()  # no HistoricalEvent query when not requested


async def test_find_similar_periods_attaches_nearby_events_within_the_window_when_requested():
    match_timestamp = datetime(2020, 1, 1, tzinfo=UTC)
    events = [
        SimpleNamespace(title="Fed rate decision", event_date=match_timestamp + timedelta(days=4)),
        SimpleNamespace(title="Far away event", event_date=match_timestamp + timedelta(days=60)),
    ]
    session_factory, session = _event_session_factory(events)
    engine = SimilarMarketEngine(session_factory)

    with (
        patch(
            "app.services.similar_market.engine.get_series",
            AsyncMock(return_value=_history_rows(32, base=match_timestamp)),
        ),
        patch(
            "app.services.similar_market.engine.build_regime_index",
            AsyncMock(return_value=_empty_regime_index()),
        ),
    ):
        matches = await engine.find_similar_periods(
            "ETH", object, Timeframe.DAILY, k=1, include_nearby_events=True
        )

    assert len(matches) == 1
    assert matches[0]["date"] == match_timestamp
    assert [e["title"] for e in matches[0]["nearby_events"]] == ["Fed rate decision"]
    session.scalars.assert_awaited_once()


async def test_find_similar_periods_regime_aware_prefers_same_regime_matches():
    base = datetime(2020, 1, 1, tzinfo=UTC)
    # Days 0-7 are the RSI-matching candidates (RSI 30-37, close to the
    # current row's 31.0), tagged BULL (0-3) or BEAR (4-7) via a patched
    # reconstruct_regime_at. Days 8-28 are far-RSI padding -- both to clear
    # _MIN_HISTORY_LENGTH (30 rows total) and so find_similar_episodes'
    # default exclude_recent=5 window falls on the padding, not the
    # candidates. RSI distance alone would prefer days 0-3 (closer to 31)
    # over 4-7 -- regime-aware filtering to BEAR (the reconstructed
    # "current"/day-29 regime) must override that.
    rows = [
        SimpleNamespace(
            timestamp=base + timedelta(days=i), rsi=30.0 + i, volatility=None, return_pct=0.01
        )
        for i in range(8)
    ]
    rows += [
        SimpleNamespace(
            timestamp=base + timedelta(days=i), rsi=99.0, volatility=None, return_pct=0.01
        )
        for i in range(8, 29)
    ]
    rows.append(
        SimpleNamespace(
            timestamp=base + timedelta(days=29), rsi=31.0, volatility=None, return_pct=0.01
        )
    )

    def fake_reconstruct(regime_index, timestamp):
        day = (timestamp - base).days
        return MarketRegime.BEAR if day >= 4 else MarketRegime.BULL

    session_factory, _ = _event_session_factory([])
    engine = SimilarMarketEngine(session_factory)

    with (
        patch("app.services.similar_market.engine.get_series", AsyncMock(return_value=rows)),
        patch(
            "app.services.similar_market.engine.build_regime_index",
            AsyncMock(return_value=_empty_regime_index()),
        ),
        patch(
            "app.services.similar_market.engine.reconstruct_regime_at",
            side_effect=fake_reconstruct,
        ),
    ):
        matches = await engine.find_similar_periods(
            "ETH", object, Timeframe.DAILY, k=2, regime_aware=True
        )

    assert len(matches) == 2
    assert all(m["market_regime"] == "bear" for m in matches)


async def test_find_similar_periods_not_regime_aware_by_default():
    base = datetime(2020, 1, 1, tzinfo=UTC)
    rows = _history_rows(32, base=base)
    call_count = 0

    def fake_reconstruct(regime_index, timestamp):
        nonlocal call_count
        call_count += 1
        return MarketRegime.BULL

    session_factory, _ = _event_session_factory([])
    engine = SimilarMarketEngine(session_factory)

    with (
        patch("app.services.similar_market.engine.get_series", AsyncMock(return_value=rows)),
        patch(
            "app.services.similar_market.engine.build_regime_index",
            AsyncMock(return_value=_empty_regime_index()),
        ),
        patch(
            "app.services.similar_market.engine.reconstruct_regime_at",
            side_effect=fake_reconstruct,
        ),
    ):
        matches = await engine.find_similar_periods("ETH", object, Timeframe.DAILY, k=1)

    assert len(matches) == 1
    # reconstruct_regime_at is still called once for the post-hoc per-match
    # tagging (unconditional), but not for every row building an eager
    # regime_series -- default (regime_aware=False) stays cheap.
    assert call_count == 1
