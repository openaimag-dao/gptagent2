from app.database.models import AssetClass, AssetPrice
from app.services.signals.engine import compute_signal


def asset(
    symbol: str, change_pct_24h: float | None = None, change_24h: float | None = None
) -> AssetPrice:
    return AssetPrice(
        symbol=symbol,
        name=symbol,
        asset_class=AssetClass.MACRO,
        price=100.0,
        change_pct_24h=change_pct_24h,
        change_24h=change_24h,
        source="test",
    )


def test_all_bullish_factors_trigger():
    assets = [
        asset("NASDAQ", change_pct_24h=1.0),
        asset("DXY", change_pct_24h=-0.5),
        asset("FEDRATE", change_24h=-0.25),
    ]

    result = compute_signal(assets, etf_sentiment=2.0)

    assert result["bull_score"] == 2 + 3 + 5 + 4  # nasdaq_up + dxy_down + etf_inflow + fed_dovish
    assert result["bear_score"] == 0
    assert result["net_score"] == result["bull_score"]
    assert result["confidence_pct"] == 100


def test_all_bearish_factors_trigger():
    assets = [
        asset("GOLD", change_pct_24h=0.8),
        asset("VIX", change_pct_24h=5.0),
        asset("US10Y", change_24h=0.05),
    ]

    result = compute_signal(assets, etf_sentiment=None)

    assert result["bull_score"] == 0
    assert result["bear_score"] == 1 + 3 + 2  # gold_up + vix_up + us10y_up
    assert result["net_score"] == -result["bear_score"]


def test_missing_data_lowers_confidence_but_does_not_crash():
    result = compute_signal([], etf_sentiment=None)

    assert result["bull_score"] == 0
    assert result["bear_score"] == 0
    assert result["confidence_pct"] == 0
    assert all(f["triggered"] is None for f in result["factors"].values())


def test_mixed_signals_partially_cancel():
    assets = [
        asset("NASDAQ", change_pct_24h=1.0),  # bull +2
        asset("VIX", change_pct_24h=5.0),  # bear +3
    ]

    result = compute_signal(assets, etf_sentiment=None)

    assert result["bull_score"] == 2
    assert result["bear_score"] == 3
    assert result["net_score"] == -1
    # available_weight = 2 + 3 = 5; confidence = round(100 * 1 / 5) = 20
    assert result["confidence_pct"] == 20
