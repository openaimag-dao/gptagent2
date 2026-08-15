from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.trade_setup.engine import (
    TradeSetup,
    backtest_trade_setup_for_symbol,
    backtest_trade_setup_rule,
    build_trade_setup,
    compute_trade_setup_expectancy,
    direction_to_side,
    evaluate_trade_setup_for_symbol,
    simulate_trade_outcome,
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
    # no stored history for this mocked session -- honestly None, not a
    # fabricated backtest, but the key must always be present.
    assert "trade_economics" in result


def _bar(high, low, close):
    return SimpleNamespace(high=high, low=low, close=close)


# ---- POST-V9 Phase 9: simulate_trade_outcome ----


def test_simulate_trade_outcome_buy_target_hit_first():
    window = [_bar(105, 99, 104), _bar(115, 110, 112)]  # day 2 high=115 >= target 110
    result = simulate_trade_outcome(100.0, 90.0, 110.0, "BUY", window)
    assert result["outcome"] == "target_hit"
    assert result["days_to_target"] == 2
    assert result["days_to_stop"] is None
    assert result["realized_return_pct"] == 10.0


def test_simulate_trade_outcome_buy_stop_hit_first():
    window = [_bar(102, 89, 90)]  # low=89 <= stop 90
    result = simulate_trade_outcome(100.0, 90.0, 110.0, "BUY", window)
    assert result["outcome"] == "stop_hit"
    assert result["days_to_stop"] == 1
    assert result["realized_return_pct"] == -10.0


def test_simulate_trade_outcome_sell_target_hit_first():
    # SELL: target below entry, stop above entry
    window = [_bar(102, 88, 90)]  # low=88 <= target 90
    result = simulate_trade_outcome(100.0, 110.0, 90.0, "SELL", window)
    assert result["outcome"] == "target_hit"
    assert result["realized_return_pct"] == 10.0  # short profits when price falls


def test_simulate_trade_outcome_sell_stop_hit_first():
    window = [_bar(111, 95, 108)]  # high=111 >= stop 110
    result = simulate_trade_outcome(100.0, 110.0, 90.0, "SELL", window)
    assert result["outcome"] == "stop_hit"
    assert result["realized_return_pct"] == -10.0


def test_simulate_trade_outcome_same_bar_ambiguity_resolves_to_stop():
    # one bar's range spans both stop (90) and target (110) -- can't tell
    # which happened first from daily OHLC, must never claim the win.
    window = [_bar(115, 85, 100)]
    result = simulate_trade_outcome(100.0, 90.0, 110.0, "BUY", window)
    assert result["outcome"] == "stop_hit"


def test_simulate_trade_outcome_open_when_neither_hit():
    window = [_bar(105, 95, 102), _bar(107, 96, 103)]
    result = simulate_trade_outcome(100.0, 90.0, 120.0, "BUY", window)
    assert result["outcome"] == "open"
    assert result["days_to_target"] is None
    assert result["days_to_stop"] is None
    # mark-to-last-close
    assert result["realized_return_pct"] == 3.0


def test_simulate_trade_outcome_empty_window_is_open_with_no_data():
    result = simulate_trade_outcome(100.0, 90.0, 110.0, "BUY", [])
    assert result == {
        "outcome": "open",
        "realized_return_pct": None,
        "mae_pct": None,
        "mfe_pct": None,
        "days_to_target": None,
        "days_to_stop": None,
    }


def test_simulate_trade_outcome_mae_mfe_track_worst_and_best_excursion():
    window = [_bar(103, 92, 95), _bar(108, 94, 107)]
    result = simulate_trade_outcome(100.0, 85.0, 120.0, "BUY", window)
    assert result["outcome"] == "open"
    # worst low across both bars is 92 -> adverse = 8 -> 8%
    assert result["mae_pct"] == 8.0
    # best high across both bars is 108 -> favorable = 8 -> 8%
    assert result["mfe_pct"] == 8.0


# ---- POST-V9 Phase 9: backtest_trade_setup_rule ----


def test_backtest_trade_setup_rule_replays_every_entry_with_forward_data():
    rows = [_bar(101, 99, 100), _bar(106, 99, 105), _bar(107, 100, 106)]
    outcomes = backtest_trade_setup_rule("BUY", 5.0, 5.0, rows, max_holding_days=2)
    # last row has no forward window -> skipped; first two entries produce outcomes
    assert len(outcomes) == 2


def test_backtest_trade_setup_rule_empty_history_is_empty():
    assert backtest_trade_setup_rule("BUY", 5.0, 5.0, [], max_holding_days=5) == []


# ---- POST-V9 Phase 9: compute_trade_setup_expectancy ----


def test_compute_trade_setup_expectancy_none_when_no_outcomes():
    assert compute_trade_setup_expectancy([]) is None


def test_compute_trade_setup_expectancy_aggregates_wins_and_losses():
    outcomes = [
        {
            "outcome": "target_hit",
            "realized_return_pct": 10.0,
            "mae_pct": 1.0,
            "mfe_pct": 10.0,
            "days_to_target": 3,
            "days_to_stop": None,
        },
        {
            "outcome": "stop_hit",
            "realized_return_pct": -5.0,
            "mae_pct": 5.0,
            "mfe_pct": 1.0,
            "days_to_target": None,
            "days_to_stop": 2,
        },
    ]
    result = compute_trade_setup_expectancy(outcomes, min_sample_size=1, reliable_sample_size=2)
    assert result["sample_count"] == 2
    assert result["win_rate_pct"] == 50.0
    assert result["target_hit_count"] == 1
    assert result["stop_hit_count"] == 1
    assert result["avg_mae_pct"] == 3.0
    assert result["avg_mfe_pct"] == 5.5
    assert result["avg_days_to_target"] == 3.0
    assert result["avg_days_to_stop"] == 2.0
    assert result["sample_sufficiency"] == "reliable"


def test_compute_trade_setup_expectancy_excludes_open_returns_from_hit_counts_only():
    outcomes = [
        {
            "outcome": "open",
            "realized_return_pct": 1.0,
            "mae_pct": 0.5,
            "mfe_pct": 1.5,
            "days_to_target": None,
            "days_to_stop": None,
        }
    ]
    result = compute_trade_setup_expectancy(outcomes)
    # "open" still counts toward the sample (it has a realized_return_pct
    # as of window exhaustion) but contributes to neither hit count.
    assert result["sample_count"] == 1
    assert result["target_hit_count"] == 0
    assert result["stop_hit_count"] == 0
    assert result["open_count"] == 1
    assert result["avg_days_to_target"] is None
    assert result["avg_days_to_stop"] is None


def test_compute_trade_setup_expectancy_reports_insufficient_below_min_sample():
    outcomes = [
        {
            "outcome": "target_hit",
            "realized_return_pct": 1.0,
            "mae_pct": 0.1,
            "mfe_pct": 1.0,
            "days_to_target": 1,
            "days_to_stop": None,
        }
    ]
    result = compute_trade_setup_expectancy(outcomes, min_sample_size=30, reliable_sample_size=100)
    assert result["sample_sufficiency"] == "insufficient"


# ---- POST-V9 Phase 9: backtest_trade_setup_for_symbol ----


def _setup(side="BUY", entry=100.0, stop=90.0, target=120.0):
    return TradeSetup(
        symbol="BTC",
        horizon="24h",
        recommendation="TRADE_OK",
        direction="Bullish",
        side=side,
        entry_price=entry,
        stop_loss_price=stop,
        take_profit_price=target,
        risk_reward_ratio=2.0,
        invalidation_level=None,
        breakout_level=None,
        probability_pct=70,
        conviction_tier="high",
        reasons=[],
    )


async def test_backtest_trade_setup_for_symbol_none_when_no_side():
    setup = _setup(side=None)
    result = await backtest_trade_setup_for_symbol(MagicMock(), "BTC", setup)
    assert result is None


async def test_backtest_trade_setup_for_symbol_none_when_symbol_unknown():
    setup = _setup()
    with patch(
        "app.services.trade_setup.engine.find_symbol_config",
        return_value=None,
    ):
        result = await backtest_trade_setup_for_symbol(MagicMock(), "NOPE", setup)
    assert result is None


async def test_backtest_trade_setup_for_symbol_none_without_enough_history():
    setup = _setup()
    with (
        patch(
            "app.services.trade_setup.engine.find_symbol_config",
            return_value=SimpleNamespace(model=object(), symbol="BTC"),
        ),
        patch(
            "app.services.trade_setup.engine.get_series",
            AsyncMock(return_value=[_bar(101, 99, 100)]),
        ),
    ):
        result = await backtest_trade_setup_for_symbol(MagicMock(), "BTC", setup)
    assert result is None


async def test_backtest_trade_setup_for_symbol_computes_expectancy_from_history():
    setup = _setup(side="BUY", entry=100.0, stop=90.0, target=120.0)
    rows = [_bar(101, 99, 100), _bar(125, 100, 110), _bar(106, 100, 101)]
    with (
        patch(
            "app.services.trade_setup.engine.find_symbol_config",
            return_value=SimpleNamespace(model=object(), symbol="BTC"),
        ),
        patch(
            "app.services.trade_setup.engine.get_series",
            AsyncMock(return_value=rows),
        ),
    ):
        result = await backtest_trade_setup_for_symbol(MagicMock(), "BTC", setup)
    assert result is not None
    assert result["sample_count"] >= 1
