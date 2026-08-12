import pytest

from app.services.backtest.conditions import Condition, evaluate_condition, evaluate_rule
from app.services.backtest.engine import universe_caveat
from app.services.backtest.metrics import (
    apply_trading_costs,
    compute_avg_loss_pct,
    compute_avg_return_pct,
    compute_avg_win_pct,
    compute_backtest_metrics,
    compute_cagr_pct,
    compute_calmar_ratio,
    compute_cvar_pct,
    compute_expectancy_pct,
    compute_max_drawdown_pct,
    compute_profit_factor,
    compute_sharpe_ratio,
    compute_sortino_ratio,
    compute_var_pct,
    compute_win_rate_pct,
)


def test_win_rate_counts_positive_returns():
    assert compute_win_rate_pct([0.01, -0.02, 0.03, -0.01]) == 50.0


def test_win_rate_empty_is_none():
    assert compute_win_rate_pct([]) is None


def test_avg_return():
    assert compute_avg_return_pct([0.02, -0.02, 0.04]) == round(100 * 0.04 / 3, 4)


def test_max_drawdown_all_gains_is_zero():
    assert compute_max_drawdown_pct([0.01, 0.02, 0.03]) == 0.0


def test_max_drawdown_detects_a_real_drop():
    # equity: 1 -> 1.10 -> 0.99 (peak 1.10, trough 0.99) -> drawdown = 0.10/1.10 = 9.09%
    result = compute_max_drawdown_pct([0.10, -0.10])
    assert result == round(100 * (1.10 - 0.99) / 1.10, 2)


def test_profit_factor_no_losses_is_none():
    assert compute_profit_factor([0.01, 0.02]) is None


def test_profit_factor_computes_gains_over_losses():
    result = compute_profit_factor([0.04, -0.02])
    assert result == round(0.04 / 0.02, 3)


def test_sharpe_ratio_needs_at_least_two_samples():
    assert compute_sharpe_ratio([0.01]) is None


def test_sharpe_ratio_zero_variance_is_none():
    assert compute_sharpe_ratio([0.01, 0.01, 0.01]) is None


def test_sharpe_ratio_computes_for_varying_returns():
    result = compute_sharpe_ratio([0.01, -0.01, 0.02, -0.02, 0.01])
    assert result is not None


def test_compute_backtest_metrics_empty_is_none():
    assert compute_backtest_metrics([]) is None


def test_compute_backtest_metrics_shape():
    result = compute_backtest_metrics([0.01, 0.02, -0.01])
    assert result["occurrences"] == 3
    assert set(result.keys()) == {
        "occurrences",
        "win_rate_pct",
        "avg_return_pct",
        "max_drawdown_pct",
        "profit_factor",
        "sharpe_ratio",
        "sortino_ratio",
        "calmar_ratio",
        "cagr_pct",
        "var_95_pct",
        "cvar_95_pct",
        "expectancy_pct",
        "avg_win_pct",
        "avg_loss_pct",
    }


def test_sortino_ignores_upside_variance():
    # All gains but varying magnitude: downside deviation is 0 -> undefined.
    assert compute_sortino_ratio([0.01, 0.02, 0.03]) is None


def test_sortino_penalizes_only_losses():
    result = compute_sortino_ratio([0.02, -0.01, 0.03, -0.02])
    assert result is not None


def test_sortino_needs_at_least_two_samples():
    assert compute_sortino_ratio([0.01]) is None


def test_calmar_none_without_drawdown():
    assert compute_calmar_ratio([0.01, 0.02, 0.03]) is None


def test_calmar_computes_with_drawdown():
    result = compute_calmar_ratio([0.10, -0.10])
    assert result is not None


def test_cagr_empty_is_none():
    assert compute_cagr_pct([]) is None


def test_cagr_positive_for_winning_sequence():
    result = compute_cagr_pct([0.01, 0.01, 0.01])
    assert result is not None
    assert result > 0


def test_var_is_positive_magnitude_of_tail_loss():
    result = compute_var_pct([-0.05, -0.02, 0.01, 0.02, 0.03], confidence=0.8)
    assert result is not None
    assert result > 0


def test_var_needs_at_least_two_samples():
    assert compute_var_pct([0.01]) is None


def test_cvar_averages_the_worst_tail():
    # confidence=0.75 over 4 samples -> cutoff = int(0.25 * 4) = 1 worst sample
    result = compute_cvar_pct([-0.10, -0.05, 0.01, 0.02], confidence=0.75)
    assert result == round(-100 * -0.10, 3)


def test_cvar_averages_multiple_tail_samples():
    # confidence=0.5 over 4 samples -> cutoff = int(0.5 * 4) = 2 worst samples
    result = compute_cvar_pct([-0.10, -0.05, 0.01, 0.02], confidence=0.5)
    assert result == round(-100 * (-0.10 - 0.05) / 2, 3)


def test_expectancy_matches_avg_return():
    returns = [0.02, -0.01, 0.03]
    assert compute_expectancy_pct(returns) == compute_avg_return_pct(returns)


def test_avg_win_and_avg_loss():
    returns = [0.02, 0.04, -0.01, -0.03]
    assert compute_avg_win_pct(returns) == round(100 * (0.02 + 0.04) / 2, 4)
    assert compute_avg_loss_pct(returns) == round(-100 * (-0.01 - 0.03) / 2, 4)


def test_avg_win_none_without_wins():
    assert compute_avg_win_pct([-0.01, -0.02]) is None


def test_avg_loss_none_without_losses():
    assert compute_avg_loss_pct([0.01, 0.02]) is None


def test_apply_trading_costs_subtracts_round_trip_cost():
    result = apply_trading_costs([0.05, -0.02], fee_pct=0.1, slippage_pct=0.05)
    assert result == [0.05 - 0.0015, -0.02 - 0.0015]


def test_apply_trading_costs_empty_list():
    assert apply_trading_costs([]) == []


def test_evaluate_condition_gt():
    condition = Condition(symbol="BTC", field="rsi", operator="gt", value=70.0)
    assert evaluate_condition({"rsi": 75.0}, condition) is True
    assert evaluate_condition({"rsi": 65.0}, condition) is False


def test_evaluate_condition_missing_field_is_none():
    condition = Condition(symbol="BTC", field="rsi", operator="gt", value=70.0)
    assert evaluate_condition({"rsi": None}, condition) is None
    assert evaluate_condition({}, condition) is None


def test_condition_rejects_unsupported_operator():
    with pytest.raises(ValueError):
        Condition(symbol="BTC", field="rsi", operator="nope", value=1.0)


def test_evaluate_rule_all_conditions_must_hold():
    conditions = [
        Condition(symbol="DXY", field="return_pct", operator="lt", value=0.0),
        Condition(symbol="NASDAQ", field="rsi", operator="gt", value=60.0),
    ]
    rows_by_symbol = {
        "DXY": {"return_pct": -0.01},
        "NASDAQ": {"rsi": 65.0},
    }
    assert evaluate_rule(rows_by_symbol, conditions) is True


def test_evaluate_rule_one_condition_false_means_rule_false():
    conditions = [
        Condition(symbol="DXY", field="return_pct", operator="lt", value=0.0),
        Condition(symbol="NASDAQ", field="rsi", operator="gt", value=60.0),
    ]
    rows_by_symbol = {
        "DXY": {"return_pct": 0.01},  # fails the condition
        "NASDAQ": {"rsi": 65.0},
    }
    assert evaluate_rule(rows_by_symbol, conditions) is False


def test_evaluate_rule_missing_symbol_data_is_none_not_false():
    conditions = [Condition(symbol="DXY", field="return_pct", operator="lt", value=0.0)]
    assert evaluate_rule({"DXY": None}, conditions) is None
    assert evaluate_rule({}, conditions) is None


def test_evaluate_rule_no_conditions_is_none():
    assert evaluate_rule({}, []) is None


def test_universe_caveat_none_for_crypto():
    assert universe_caveat("BTC") is None


def test_universe_caveat_none_for_index():
    assert universe_caveat("NASDAQ") is None


def test_universe_caveat_present_for_fixed_stock_roster():
    for symbol in ("AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL"):
        caveat = universe_caveat(symbol)
        assert caveat is not None
        assert "survivor" in caveat
