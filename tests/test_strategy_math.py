from app.services.backtest.strategy import (
    apply_position_size,
    monte_carlo_simulation,
    simulate_trade_exit,
)


def test_simulate_trade_exit_none_when_empty():
    assert simulate_trade_exit([]) is None


def test_simulate_trade_exit_no_limits_compounds_fully():
    result = simulate_trade_exit([0.05, 0.05])
    assert round(result, 6) == round(1.05 * 1.05 - 1, 6)


def test_simulate_trade_exit_stops_at_stop_loss():
    # -3% day 1, -3% day 2 (cumulative ~-5.9%), -3% day 3 -> should exit at -5% cap
    result = simulate_trade_exit([-0.03, -0.03, -0.03], stop_loss_pct=0.05)
    assert result == -0.05


def test_simulate_trade_exit_stops_at_take_profit():
    result = simulate_trade_exit([0.03, 0.03, 0.03], take_profit_pct=0.05)
    assert result == 0.05


def test_simulate_trade_exit_never_triggers_returns_full_horizon():
    result = simulate_trade_exit([0.01, -0.01, 0.01], stop_loss_pct=0.5, take_profit_pct=0.5)
    assert round(result, 6) == round(1.01 * 0.99 * 1.01 - 1, 6)


def test_apply_position_size_scales_return():
    assert apply_position_size(0.10, 0.5) == 0.05
    assert apply_position_size(-0.10, 0.25) == -0.025


def test_monte_carlo_none_below_two_trades():
    assert monte_carlo_simulation([0.05]) is None


def test_monte_carlo_deterministic_with_seed():
    trades = [0.05, -0.03, 0.02, -0.01, 0.04]
    a = monte_carlo_simulation(trades, n_simulations=200, seed=42)
    b = monte_carlo_simulation(trades, n_simulations=200, seed=42)
    assert a == b


def test_monte_carlo_returns_expected_shape():
    trades = [0.05, -0.03, 0.02, -0.01, 0.04, 0.03, -0.02]
    result = monte_carlo_simulation(trades, n_simulations=500, seed=1)
    assert result is not None
    assert result["n_simulations"] == 500
    assert result["trades_per_sim"] == len(trades)
    assert result["total_return_p5_pct"] <= result["total_return_p50_pct"]
    assert result["total_return_p50_pct"] <= result["total_return_p95_pct"]
    assert result["max_drawdown_p50_pct"] <= result["max_drawdown_p95_pct"]


def test_monte_carlo_all_positive_trades_never_draws_down():
    trades = [0.01, 0.02, 0.03]
    result = monte_carlo_simulation(trades, n_simulations=200, seed=7)
    assert result["max_drawdown_p95_pct"] == 0.0


# ---- Forecast Intelligence Upgrade: probability of profit/loss/ruin --------


def test_monte_carlo_all_positive_trades_are_certain_profit_never_ruin():
    trades = [0.01, 0.02, 0.03]
    result = monte_carlo_simulation(trades, n_simulations=200, seed=7)
    assert result["probability_of_profit_pct"] == 100.0
    assert result["probability_of_loss_pct"] == 0.0
    assert result["probability_of_ruin_pct"] == 0.0


def test_monte_carlo_all_negative_trades_are_certain_loss():
    trades = [-0.05, -0.08, -0.10]
    result = monte_carlo_simulation(trades, n_simulations=200, seed=3)
    assert result["probability_of_loss_pct"] == 100.0
    assert result["probability_of_profit_pct"] == 0.0


def test_monte_carlo_ruin_threshold_is_configurable_and_returned():
    trades = [0.05, -0.03, 0.02, -0.01]
    result = monte_carlo_simulation(trades, n_simulations=200, seed=5, ruin_drawdown_pct=10.0)
    assert result["ruin_drawdown_pct"] == 10.0
    # A tighter ruin threshold can only ever find equal-or-more ruin paths
    # than a looser one over the exact same simulated outcomes.
    looser = monte_carlo_simulation(trades, n_simulations=200, seed=5, ruin_drawdown_pct=90.0)
    assert result["probability_of_ruin_pct"] >= looser["probability_of_ruin_pct"]


def test_monte_carlo_profit_and_loss_probabilities_are_consistent_with_percentiles():
    trades = [0.05, -0.03, 0.02, -0.01, 0.04, 0.03, -0.02]
    result = monte_carlo_simulation(trades, n_simulations=500, seed=1)
    # If the median outcome is a real profit, the majority of paths can't
    # have landed on the loss side -- a basic sanity cross-check between
    # two numbers derived from the same underlying simulated outcomes.
    if result["total_return_p50_pct"] > 0:
        assert result["probability_of_profit_pct"] > result["probability_of_loss_pct"]
