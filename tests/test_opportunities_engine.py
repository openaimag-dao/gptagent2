from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.opportunities.engine import classify_opportunity_rating, rank_opportunities


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


def _event(symbol, direction, probability_pct, price=100.0):
    return SimpleNamespace(
        symbol=symbol,
        direction=direction,
        price=price,
        probability_pct=probability_pct,
        confidence_pct=83,
        risk_score=30.0,
        expected_continuation="likely to continue",
        reasoning="Breakout (bullish). Confirmed by: Volume.",
        computed_at=datetime(2026, 8, 3, tzinfo=UTC),
    )


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
