from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.opportunities.engine import (
    classify_opportunity_rating,
    compute_risk_adjusted_score,
    rank_opportunities,
)


def test_classify_opportunity_rating_bullish_tiers():
    assert classify_opportunity_rating("bullish", 80.0) == "Strong Buy"
    assert classify_opportunity_rating("bullish", 65.0) == "Buy"
    assert classify_opportunity_rating("bullish", 40.0) == "Watch"


def test_classify_opportunity_rating_bearish_tiers():
    assert classify_opportunity_rating("bearish", 80.0) == "Strong Sell"
    assert classify_opportunity_rating("bearish", 65.0) == "Sell"
    assert classify_opportunity_rating("bearish", 40.0) == "Watch"


def test_classify_opportunity_rating_none_probability_is_unrated():
    assert classify_opportunity_rating("bullish", None) == "Unrated"


def _event(symbol, direction, probability_pct, price=100.0, risk_score=30.0):
    return SimpleNamespace(
        symbol=symbol,
        direction=direction,
        price=price,
        probability_pct=probability_pct,
        confidence_pct=83,
        risk_score=risk_score,
        expected_continuation="likely to continue",
        reasoning="Breakout (bullish). Confirmed by: Volume.",
        computed_at=datetime(2026, 8, 3, tzinfo=UTC),
    )


def test_compute_risk_adjusted_score_discounts_by_risk():
    # 90% probability sitting right on the level (risk_score 90) is more
    # precarious than 70% probability with room to breathe (risk_score 10).
    assert compute_risk_adjusted_score(90.0, 90.0) == pytest.approx(9.0)
    assert compute_risk_adjusted_score(70.0, 10.0) == pytest.approx(63.0)


def test_compute_risk_adjusted_score_missing_risk_leaves_probability_undiscounted():
    assert compute_risk_adjusted_score(70.0, None) == 70.0


def test_compute_risk_adjusted_score_missing_probability_is_none():
    assert compute_risk_adjusted_score(None, 30.0) is None


def test_rank_opportunities_risk_adjustment_can_flip_order():
    events = [
        _event("BTC", "bullish", 90.0, risk_score=90.0),  # risk-adjusted: 9.0
        _event("ETH", "bullish", 70.0, risk_score=10.0),  # risk-adjusted: 63.0
    ]

    ranked = rank_opportunities(events)

    assert [o["symbol"] for o in ranked] == ["ETH", "BTC"]
    assert ranked[0]["risk_adjusted_score"] == 63.0
    assert ranked[1]["risk_adjusted_score"] == 9.0
    # Raw probability_pct is untouched -- only the sort order changes.
    assert ranked[0]["probability_pct"] == 70.0


def test_rank_opportunities_sorts_by_probability_descending():
    events = [
        _event("ETH", "bullish", 55.0),
        _event("BTC", "bullish", 90.0),
        _event("SOL", "bearish", 70.0),
    ]

    ranked = rank_opportunities(events)

    assert [o["symbol"] for o in ranked] == ["BTC", "SOL", "ETH"]
    assert ranked[0]["rating"] == "Strong Buy"
    assert ranked[0]["probability_pct"] == 90.0


def test_rank_opportunities_missing_probability_sorts_last():
    events = [_event("BTC", "bullish", None), _event("ETH", "bullish", 55.0)]

    ranked = rank_opportunities(events)

    assert [o["symbol"] for o in ranked] == ["ETH", "BTC"]
    assert ranked[1]["rating"] == "Unrated"


def test_rank_opportunities_respects_limit():
    events = [_event(f"SYM{i}", "bullish", float(i)) for i in range(5)]

    ranked = rank_opportunities(events, limit=2)

    assert len(ranked) == 2


# Root-cause regression: BreakoutEvent.probability_pct/risk_score are
# SQLAlchemy Numeric columns -- asyncpg hands them back as Decimal, not
# float. risk_adjusted_score was computed straight from those raw Decimals
# and never cast back to float, so the API's implicit `-> dict` response
# model (Pydantic, JSON mode) silently serialized it as a *string*
# ("63.0") instead of a number, breaking any numeric consumer. Real
# Decimal inputs here (not the plain-float SimpleNamespace fixtures
# above) are what actually catch this.
def test_rank_opportunities_risk_adjusted_score_is_float_not_decimal():
    events = [_event("BTC", "bullish", Decimal("90.0"), risk_score=Decimal("90.0"))]

    ranked = rank_opportunities(events)

    assert type(ranked[0]["risk_adjusted_score"]) is float
    assert ranked[0]["risk_adjusted_score"] == pytest.approx(9.0)
