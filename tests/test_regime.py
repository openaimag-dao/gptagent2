from app.database.models import AssetClass, AssetPrice
from app.services.analysis.regime import MarketRegime, detect_regime


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


def test_risk_on():
    assets = [
        asset("SPX", change_pct_24h=1.2),
        asset("BTC", change_pct_24h=3.0),
        asset("VIX", change_pct_24h=-5.0),
        asset("DXY", change_pct_24h=-0.3),
    ]

    regime, inputs = detect_regime(assets)

    assert regime is MarketRegime.RISK_ON
    assert inputs["btc_change_pct"] == 3.0


def test_risk_off():
    assets = [
        asset("SPX", change_pct_24h=-1.5),
        asset("BTC", change_pct_24h=-4.0),
        asset("VIX", change_pct_24h=8.0),
        asset("DXY", change_pct_24h=0.5),
    ]

    regime, _ = detect_regime(assets)

    assert regime is MarketRegime.RISK_OFF


def test_flight_to_safety_takes_priority_over_risk_off():
    assets = [
        asset("SPX", change_pct_24h=-2.0),
        asset("BTC", change_pct_24h=-3.0),
        asset("VIX", change_pct_24h=6.0),
        asset("DXY", change_pct_24h=0.2),
        asset("GOLD", change_pct_24h=1.5),
        asset("US10Y", change_24h=-0.05),
    ]

    regime, _ = detect_regime(assets)

    assert regime is MarketRegime.FLIGHT_TO_SAFETY


def test_liquidity_expansion_on_rate_cut():
    assets = [asset("FEDRATE", change_24h=-0.25)]

    regime, inputs = detect_regime(assets)

    assert regime is MarketRegime.LIQUIDITY_EXPANSION
    assert inputs["fedrate_change"] == -0.25


def test_liquidity_contraction_on_rate_hike():
    assets = [asset("FEDRATE", change_24h=0.25)]

    regime, _ = detect_regime(assets)

    assert regime is MarketRegime.LIQUIDITY_CONTRACTION


def test_neutral_when_signals_disagree():
    assets = [
        asset("SPX", change_pct_24h=1.0),
        asset("BTC", change_pct_24h=-1.0),
        asset("VIX", change_pct_24h=0.5),
        asset("DXY", change_pct_24h=0.1),
    ]

    regime, _ = detect_regime(assets)

    assert regime is MarketRegime.NEUTRAL


def test_neutral_when_data_missing():
    assert detect_regime([])[0] is MarketRegime.NEUTRAL
