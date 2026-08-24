from types import SimpleNamespace

import pytest

from app.services.futures_sim.performance import compute_performance_stats


def _trade(**overrides):
    defaults = dict(
        symbol="BTC",
        side="LONG",
        leverage=20,
        net_pnl=100.0,
        fees=4.0,
        funding=0.0,
        roi_pct=20.0,
        exit_reason="MANUAL",
        strategy_tag="manual",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_compute_performance_stats_with_no_trades_returns_zeroed_overall():
    stats = compute_performance_stats([])
    assert stats["overall"]["total_trades"] == 0
    assert stats["overall"]["winning_trades"] == 0
    assert stats["overall"]["total_pnl"] == 0.0
    assert stats["by_side"] == {}
    assert stats["by_symbol"] == {}
    assert stats["by_leverage"] == {}
    assert stats["by_strategy"] == {}


def test_overall_counts_wins_losses_and_totals_correctly():
    trades = [
        _trade(net_pnl=100.0, fees=4.0, funding=1.0, roi_pct=20.0),
        _trade(net_pnl=-50.0, fees=2.0, funding=0.5, roi_pct=-10.0),
        _trade(net_pnl=30.0, fees=1.0, funding=0.0, roi_pct=6.0),
    ]
    overall = compute_performance_stats(trades)["overall"]

    assert overall["total_trades"] == 3
    assert overall["winning_trades"] == 2
    assert overall["losing_trades"] == 1
    assert overall["total_pnl"] == pytest.approx(80.0)
    assert overall["total_fees"] == pytest.approx(7.0)
    assert overall["total_funding"] == pytest.approx(1.5)
    assert overall["win_rate_pct"] == pytest.approx(66.67, rel=1e-3)


def test_liquidations_are_counted_separately_from_ordinary_losses():
    trades = [
        _trade(net_pnl=-500.0, roi_pct=-100.0, exit_reason="LIQUIDATION"),
        _trade(net_pnl=-10.0, roi_pct=-2.0, exit_reason="STOP_LOSS"),
    ]
    overall = compute_performance_stats(trades)["overall"]
    assert overall["liquidations"] == 1
    assert overall["losing_trades"] == 2


def test_breakdown_by_side_separates_long_and_short():
    trades = [
        _trade(side="LONG", net_pnl=100.0, roi_pct=20.0),
        _trade(side="LONG", net_pnl=50.0, roi_pct=10.0),
        _trade(side="SHORT", net_pnl=-30.0, roi_pct=-6.0),
    ]
    by_side = compute_performance_stats(trades)["by_side"]
    assert set(by_side.keys()) == {"LONG", "SHORT"}
    assert by_side["LONG"]["total_trades"] == 2
    assert by_side["LONG"]["total_pnl"] == pytest.approx(150.0)
    assert by_side["SHORT"]["total_trades"] == 1


def test_breakdown_by_symbol_and_leverage_and_strategy():
    trades = [
        _trade(symbol="BTC", leverage=20, strategy_tag="manual"),
        _trade(symbol="BTC", leverage=10, strategy_tag="ai_assisted"),
        _trade(symbol="ETH", leverage=20, strategy_tag="manual"),
    ]
    stats = compute_performance_stats(trades)

    assert set(stats["by_symbol"].keys()) == {"BTC", "ETH"}
    assert stats["by_symbol"]["BTC"]["total_trades"] == 2
    assert stats["by_symbol"]["ETH"]["total_trades"] == 1

    assert set(stats["by_leverage"].keys()) == {"10", "20"}
    assert stats["by_leverage"]["20"]["total_trades"] == 2

    assert set(stats["by_strategy"].keys()) == {"manual", "ai_assisted"}
    assert stats["by_strategy"]["manual"]["total_trades"] == 2
    assert stats["by_strategy"]["ai_assisted"]["total_trades"] == 1


def test_profit_factor_and_expectancy_are_computed_from_roi_pct():
    # gains: 20% + 6% = 26%; losses: 10% -> profit factor = 26/10 = 2.6
    trades = [
        _trade(net_pnl=100.0, roi_pct=20.0),
        _trade(net_pnl=30.0, roi_pct=6.0),
        _trade(net_pnl=-50.0, roi_pct=-10.0),
    ]
    overall = compute_performance_stats(trades)["overall"]
    assert overall["profit_factor"] == pytest.approx(2.6, rel=1e-2)
    assert overall["expectancy_pct"] is not None
