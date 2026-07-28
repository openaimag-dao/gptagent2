from app.database.models import AssetClass, AssetPrice, MarketRegimeSnapshot, SignalSnapshot
from app.services.analysis.regime import MarketRegime
from app.services.consensus.engine import ConsensusResult
from app.telegram.formatters import (
    format_asset_class,
    format_consensus,
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
