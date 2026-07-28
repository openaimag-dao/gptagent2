from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.portfolio.advisor import PortfolioAdvisorEngine, compute_advice


def test_compute_advice_buy_when_signal_and_probability_both_bullish():
    advice = compute_advice(
        symbol="BTC",
        timeframe="1d",
        close=100.0,
        atr=5.0,
        net_score=3,
        prob_up_pct=60,
        prob_down_pct=20,
        prob_flat_pct=20,
    )

    assert advice.recommendation == "BUY"
    assert advice.stop_loss_price == 90.0  # 100 - 2*5
    assert advice.take_profit_price == 120.0  # 100 + 2*2*5
    assert advice.risk_reward_ratio == 2.0


def test_compute_advice_sell_when_signal_and_probability_both_bearish():
    advice = compute_advice(
        symbol="BTC",
        timeframe="1d",
        close=100.0,
        atr=5.0,
        net_score=-3,
        prob_up_pct=20,
        prob_down_pct=60,
        prob_flat_pct=20,
    )

    assert advice.recommendation == "SELL"
    assert advice.stop_loss_price == 110.0
    assert advice.take_profit_price == 80.0


def test_compute_advice_hold_when_signal_and_probability_disagree():
    advice = compute_advice(
        symbol="BTC",
        timeframe="1d",
        close=100.0,
        atr=5.0,
        net_score=3,  # bullish signal
        prob_up_pct=20,
        prob_down_pct=60,  # but bearish probability
        prob_flat_pct=20,
    )

    assert advice.recommendation == "HOLD"
    assert advice.stop_loss_price is None
    assert advice.take_profit_price is None


def test_compute_advice_hold_when_probability_is_flat_dominant():
    advice = compute_advice(
        symbol="BTC",
        timeframe="1d",
        close=100.0,
        atr=5.0,
        net_score=3,
        prob_up_pct=30,
        prob_down_pct=20,
        prob_flat_pct=50,
    )

    assert advice.recommendation == "HOLD"


def test_compute_advice_never_fabricates_levels_without_atr():
    advice = compute_advice(
        symbol="BTC",
        timeframe="1d",
        close=100.0,
        atr=None,
        net_score=3,
        prob_up_pct=60,
        prob_down_pct=20,
        prob_flat_pct=20,
    )

    assert advice.recommendation == "BUY"
    assert advice.stop_loss_price is None
    assert advice.take_profit_price is None
    assert advice.position_size_quantity is None


def test_compute_advice_position_size_only_when_portfolio_value_given():
    without_equity = compute_advice(
        symbol="BTC",
        timeframe="1d",
        close=100.0,
        atr=5.0,
        net_score=3,
        prob_up_pct=60,
        prob_down_pct=20,
        prob_flat_pct=20,
    )
    assert without_equity.position_size_quantity is None

    with_equity = compute_advice(
        symbol="BTC",
        timeframe="1d",
        close=100.0,
        atr=5.0,
        net_score=3,
        prob_up_pct=60,
        prob_down_pct=20,
        prob_flat_pct=20,
        portfolio_value=10_000.0,
        risk_pct=0.01,
    )
    # risk_amount = 100, risk_per_unit = 100 - 90 = 10 -> 10 units
    assert with_equity.position_size_quantity == 10.0


def test_compute_advice_no_position_size_for_sell():
    advice = compute_advice(
        symbol="BTC",
        timeframe="1d",
        close=100.0,
        atr=5.0,
        net_score=-3,
        prob_up_pct=20,
        prob_down_pct=60,
        prob_flat_pct=20,
        portfolio_value=10_000.0,
    )
    assert advice.recommendation == "SELL"
    assert advice.position_size_quantity is None


async def test_portfolio_advisor_engine_returns_none_for_unknown_symbol():
    engine = PortfolioAdvisorEngine(AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())

    result = await engine.advise("NOT_A_REAL_SYMBOL")

    assert result is None


async def test_portfolio_advisor_engine_returns_none_when_signal_missing():
    signal_engine = AsyncMock()
    signal_engine.get_latest.return_value = None
    probability_engine = AsyncMock()
    probability_engine.get_latest.return_value = SimpleNamespace(
        prob_up_pct=50, prob_down_pct=30, prob_flat_pct=20
    )

    engine = PortfolioAdvisorEngine(AsyncMock(), signal_engine, probability_engine, AsyncMock())

    fake_row = SimpleNamespace(close=100.0, atr=5.0)
    with patch("app.services.portfolio.advisor.get_series", AsyncMock(return_value=[fake_row])):
        result = await engine.advise("BTC")

    assert result is None
    signal_engine.get_latest.assert_awaited_once()


async def test_portfolio_advisor_engine_returns_none_when_probability_missing():
    signal_engine = AsyncMock()
    signal_engine.get_latest.return_value = SimpleNamespace(net_score=3)
    probability_engine = AsyncMock()
    probability_engine.get_latest.return_value = None

    engine = PortfolioAdvisorEngine(AsyncMock(), signal_engine, probability_engine, AsyncMock())

    fake_row = SimpleNamespace(close=100.0, atr=5.0)
    with patch("app.services.portfolio.advisor.get_series", AsyncMock(return_value=[fake_row])):
        result = await engine.advise("BTC")

    assert result is None
    probability_engine.get_latest.assert_awaited_once()
