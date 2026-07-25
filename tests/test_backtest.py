import pytest

from app.services.backtest.conditions import Condition, evaluate_condition, evaluate_rule
from app.services.backtest.metrics import (
    compute_avg_return_pct,
    compute_backtest_metrics,
    compute_max_drawdown_pct,
    compute_profit_factor,
    compute_sharpe_ratio,
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
    }


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
