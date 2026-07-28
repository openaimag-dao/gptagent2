from datetime import UTC, datetime

from app.database.models import AssetClass, AssetPrice, MarketRegimeSnapshot, SignalSnapshot
from app.services.analysis.regime import MarketRegime
from app.services.consensus.engine import ConsensusResult
from app.telegram.formatters import (
    format_advice,
    format_asset_class,
    format_consensus,
    format_learning,
    format_market_summary,
    format_regime,
    format_signal,
    format_single_asset,
)


def _asset(
    symbol: str,
    asset_class: AssetClass,
    price: float,
    change_pct_24h: float | None = None,
) -> AssetPrice:
    return AssetPrice(
        symbol=symbol,
        name=symbol,
        asset_class=asset_class,
        price=price,
        change_pct_24h=change_pct_24h,
        source="test",
    )


def test_format_market_summary_empty():
    assert "No market data" in format_market_summary([])


def test_format_market_summary_groups_by_class():
    assets = [
        _asset("BTC", AssetClass.CRYPTO, 65000.0, 1.5),
        _asset("NASDAQ", AssetClass.INDEX, 18000.0, -0.5),
    ]

    text = format_market_summary(assets)

    assert "Crypto" in text
    assert "Indices" in text
    assert "BTC: 65,000.00" in text
    assert "NASDAQ: 18,000.00" in text


def test_format_asset_class_filters_correctly():
    assets = [
        _asset("BTC", AssetClass.CRYPTO, 65000.0, 1.5),
        _asset("NASDAQ", AssetClass.INDEX, 18000.0, -0.5),
    ]

    text = format_asset_class(assets, AssetClass.CRYPTO, "Crypto Market")

    assert "BTC" in text
    assert "NASDAQ" not in text


def test_format_single_asset_missing():
    assert "No data available" in format_single_asset("BTC", None)


def test_format_single_asset_present():
    asset = _asset("BTC", AssetClass.CRYPTO, 65000.0, 1.5)
    text = format_single_asset("BTC", asset)
    assert "65,000.00" in text
    assert "+1.50%" in text


def test_format_signal_missing():
    assert "No signal has been computed" in format_signal(None)


def test_format_signal_present():
    snapshot = SignalSnapshot(
        bull_score=5,
        bear_score=2,
        net_score=3,
        confidence_pct=60,
        factors={"nasdaq_up": {"points": 2, "triggered": True}},
    )
    text = format_signal(snapshot)
    assert "Bull score: 5" in text
    assert "Nasdaq up" in text
    assert "_" not in text


def test_format_regime_present():
    snapshot = MarketRegimeSnapshot(regime=MarketRegime.RISK_ON, inputs={})
    assert "Risk On" in format_regime(snapshot)


def test_format_consensus_none():
    assert "nothing to tally" in format_consensus(None)


def test_format_consensus_present():
    result = ConsensusResult(
        bullish_pct=70.0,
        bearish_pct=30.0,
        neutral_pct=0.0,
        agreement_score=70.0,
        bullish_agents=["news", "equity"],
        bearish_agents=["macro"],
    )
    text = format_consensus(result)
    assert "Bullish 70.0%" in text
    assert "news, equity" in text
    assert "macro" in text


def test_format_learning_none():
    text = format_learning(None, "BTC", "1d")
    assert "No graded predictions" in text
    assert "BTC/1d" in text


def test_format_learning_present():
    result = {
        "symbol": "BTC",
        "timeframe": "1d",
        "evaluated_predictions": 2,
        "accuracy_pct": 50.0,
        "recent": [
            {
                "reference_timestamp": datetime(2026, 1, 1, tzinfo=UTC),
                "predicted": "up",
                "realized": "up",
                "correct": True,
                "realized_return_pct": 1.5,
            },
            {
                "reference_timestamp": datetime(2026, 1, 2, tzinfo=UTC),
                "predicted": "up",
                "realized": "down",
                "correct": False,
                "realized_return_pct": -0.8,
            },
        ],
    }
    text = format_learning(result, "BTC", "1d")
    assert "Accuracy: 50.0%" in text
    assert "correct" in text
    assert "wrong" in text


def test_format_advice_none():
    text = format_advice(None, "BTC", "1d")
    assert "Not enough data yet" in text
    assert "BTC/1d" in text


def test_format_advice_buy_with_levels():
    advice = {
        "symbol": "BTC",
        "timeframe": "1d",
        "recommendation": "BUY",
        "reasoning": (
            "Signal Engine net score 3 (bullish) agrees with the empirical probability read."
        ),
        "signal_net_score": 3,
        "probability": {"up": 60, "down": 20, "flat": 20},
        "entry_reference_price": 100.0,
        "atr": 5.0,
        "stop_loss_price": 90.0,
        "take_profit_price": 120.0,
        "risk_reward_ratio": 2.0,
        "position_size_quantity": 10.0,
        "position_size_note": (
            "Sized to risk 1.0% of portfolio equity (100.00) if stopped out at 90.0."
        ),
    }
    text = format_advice(advice, "BTC", "1d")
    assert "BTC ADVICE" in text
    assert "BUY" in text
    assert "Stop-loss: 90.00" in text
    assert "Take-profit: 120.00" in text
    assert "Position size: 10.0" in text


def test_format_advice_hold_no_levels():
    advice = {
        "symbol": "BTC",
        "timeframe": "1d",
        "recommendation": "HOLD",
        "reasoning": (
            "Signal Engine net score 3 (bullish) disagrees with the empirical probability read."
        ),
        "signal_net_score": 3,
        "probability": {"up": 20, "down": 60, "flat": 20},
        "entry_reference_price": 100.0,
        "atr": 5.0,
        "stop_loss_price": None,
        "take_profit_price": None,
        "risk_reward_ratio": None,
        "position_size_quantity": None,
        "position_size_note": None,
    }
    text = format_advice(advice, "BTC", "1d")
    assert "HOLD" in text
    assert "Stop-loss" not in text
    assert "Position size" not in text
