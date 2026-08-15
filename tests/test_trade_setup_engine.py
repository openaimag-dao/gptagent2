from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.trade_setup.engine import (
    build_trade_setup,
    direction_to_side,
    evaluate_trade_setup_for_symbol,
)

_BULLISH_PAYLOAD = {
    "direction": "Bullish",
    "current_price": 100.0,
    "expected_volatility_pct": 5.0,  # atr = 5.0
    "key_levels": {"invalidation_level": 95.0, "breakout_level": 110.0},
    "probability_pct": 70,
    "confidence": {"tier": "high"},
}

_BEARISH_PAYLOAD = {
    "direction": "Strong Bearish",
    "current_price": 100.0,
    "expected_volatility_pct": 4.0,
    "key_levels": {"invalidation_level": 105.0, "breakout_level": 90.0},
    "probability_pct": 68,
    "confidence": {"tier": "medium"},
}

_NEUTRAL_PAYLOAD = {
    "direction": "Neutral",
    "current_price": 100.0,
    "expected_volatility_pct": 3.0,
    "key_levels": {},
    "probability_pct": 40,
    "confidence": {"tier": "low"},
}

_TRADE_OK = {"recommendation": "TRADE_OK", "reasons": []}
_NO_TRADE = {
    "recommendation": "NO_TRADE",
    "reasons": [{"code": "low_probability", "description": "too low"}],
}


def test_direction_to_side_maps_bullish_and_bearish():
    assert direction_to_side("Bullish") == "BUY"
    assert direction_to_side("Strong Bullish") == "BUY"
    assert direction_to_side("Bearish") == "SELL"
    assert direction_to_side("Strong Bearish") == "SELL"
    assert direction_to_side("Neutral") is None
    assert direction_to_side(None) is None


def test_build_trade_setup_buy_side_uses_atr_levels():
    setup = build_trade_setup(
        symbol="btc", horizon="24h", forecast_payload=_BULLISH_PAYLOAD, no_trade_result=_TRADE_OK
    )
    assert setup.symbol == "BTC"
    assert setup.recommendation == "TRADE_OK"
    assert setup.side == "BUY"
    assert setup.entry_price == 100.0
    # atr = 5.0 -> stop = 100 - 2*5 = 90, target = 100 + 2*2*5 = 120
    assert setup.stop_loss_price == 90.0
    assert setup.take_profit_price == 120.0
    assert setup.risk_reward_ratio == 2.0
    assert setup.invalidation_level == 95.0
    assert setup.breakout_level == 110.0
    assert setup.probability_pct == 70
    assert setup.conviction_tier == "high"
    assert setup.reasons == []


def test_build_trade_setup_sell_side_uses_atr_levels():
    setup = build_trade_setup(
        symbol="ETH", horizon="24h", forecast_payload=_BEARISH_PAYLOAD, no_trade_result=_TRADE_OK
    )
    assert setup.side == "SELL"
    # atr = 4.0 -> stop = 100 + 2*4 = 108, target = 100 - 2*2*4 = 84
    assert setup.stop_loss_price == 108.0
    assert setup.take_profit_price == 84.0


def test_build_trade_setup_no_directional_edge_forces_no_trade():
    setup = build_trade_setup(
        symbol="SOL", horizon="24h", forecast_payload=_NEUTRAL_PAYLOAD, no_trade_result=_TRADE_OK
    )
    assert setup.side is None
    assert setup.recommendation == "NO_TRADE"
    assert setup.stop_loss_price is None
    assert setup.take_profit_price is None
    codes = [r["code"] for r in setup.reasons]
    assert "no_directional_edge" in codes


def test_build_trade_setup_propagates_no_trade_gate_even_with_directional_edge():
    setup = build_trade_setup(
        symbol="BTC", horizon="24h", forecast_payload=_BULLISH_PAYLOAD, no_trade_result=_NO_TRADE
    )
    assert setup.recommendation == "NO_TRADE"
    codes = [r["code"] for r in setup.reasons]
    assert "low_probability" in codes
    # Directional edge existed, so the levels ARE still computed -- NO_TRADE
    # from the gate doesn't erase the underlying math, only the verdict.
    assert setup.stop_loss_price is not None


def test_build_trade_setup_no_atr_leaves_levels_none():
    payload = {**_BULLISH_PAYLOAD, "expected_volatility_pct": None}
    setup = build_trade_setup(
        symbol="BTC", horizon="24h", forecast_payload=payload, no_trade_result=_TRADE_OK
    )
    assert setup.side == "BUY"
    assert setup.stop_loss_price is None
    assert setup.take_profit_price is None


def test_to_dict_shape():
    setup = build_trade_setup(
        symbol="BTC", horizon="24h", forecast_payload=_BULLISH_PAYLOAD, no_trade_result=_TRADE_OK
    )
    payload = setup.to_dict()
    assert payload["symbol"] == "BTC"
    assert payload["horizon"] == "24h"
    assert set(payload) >= {
        "recommendation",
        "direction",
        "side",
        "entry_price",
        "stop_loss_price",
        "take_profit_price",
        "risk_reward_ratio",
        "invalidation_level",
        "breakout_level",
        "probability_pct",
        "conviction_tier",
        "reasons",
    }


async def test_evaluate_trade_setup_for_symbol_returns_none_without_a_forecast():
    forecast_engine = AsyncMock()
    forecast_engine.compute.return_value = None
    with patch("app.services.forecast.engine.build_forecast_engine", return_value=forecast_engine):
        result = await evaluate_trade_setup_for_symbol(MagicMock(), "BTC")
    assert result is None


async def test_evaluate_trade_setup_for_symbol_computes_forecast_only_once():
    forecast_engine = AsyncMock()
    forecast_engine.compute.return_value = {
        **_BULLISH_PAYLOAD,
        "sample_size": 50,
        "consensus": {"conflict_pct": 10.0},
        "forecast_status": "ACTIVE",
        "reference_timestamp": datetime.now(UTC).isoformat(),
    }

    regime_session = AsyncMock()
    regime_session.scalar.return_value = MagicMock(confidence_pct=85)
    regime_session.__aenter__.return_value = regime_session
    session_factory = MagicMock(return_value=regime_session)

    with patch("app.services.forecast.engine.build_forecast_engine", return_value=forecast_engine):
        result = await evaluate_trade_setup_for_symbol(session_factory, "btc", "24h")

    assert forecast_engine.compute.await_count == 1
    assert result["symbol"] == "BTC"
    assert result["recommendation"] == "TRADE_OK"
    assert result["side"] == "BUY"
    assert result["stop_loss_price"] == 90.0
