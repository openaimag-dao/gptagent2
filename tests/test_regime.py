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


def test_capitulation_on_extreme_drop_and_vix_spike():
    assets = [asset("BTC", change_pct_24h=-9.0), asset("VIX", change_pct_24h=20.0)]

    regime, _ = detect_regime(assets)

    assert regime is MarketRegime.CAPITULATION


def test_capitulation_takes_priority_over_risk_off():
    assets = [
        asset("SPX", change_pct_24h=-2.0),
        asset("BTC", change_pct_24h=-9.0),
        asset("VIX", change_pct_24h=20.0),
        asset("DXY", change_pct_24h=0.5),
    ]

    regime, _ = detect_regime(assets)

    assert regime is MarketRegime.CAPITULATION


def test_bull_on_strong_positive_30d_momentum():
    regime, inputs = detect_regime([], momentum_30d={"BTC": 15.0, "SPX": 12.0})

    assert regime is MarketRegime.BULL
    assert inputs["momentum_30d"] == {"BTC": 15.0, "SPX": 12.0}


def test_bear_on_strong_negative_30d_momentum():
    regime, _ = detect_regime([], momentum_30d={"BTC": -15.0, "SPX": -12.0})

    assert regime is MarketRegime.BEAR


def test_no_bull_bear_when_momentum_disagrees():
    regime, _ = detect_regime([], momentum_30d={"BTC": 15.0, "SPX": -12.0})

    assert regime is MarketRegime.NEUTRAL


def test_strong_bull_on_very_strong_positive_30d_momentum():
    regime, _ = detect_regime([], momentum_30d={"BTC": 25.0, "SPX": 22.0})

    assert regime is MarketRegime.STRONG_BULL


def test_bull_weakening_on_decelerating_momentum():
    regime, _ = detect_regime(
        [],
        momentum_30d={"BTC": 6.0, "SPX": 5.0},
        previous_momentum_30d={"BTC": 14.0, "SPX": 12.0},
    )

    assert regime is MarketRegime.BULL_WEAKENING


def test_bull_weakening_not_triggered_without_previous_momentum():
    regime, _ = detect_regime([], momentum_30d={"BTC": 6.0, "SPX": 5.0})

    assert regime is not MarketRegime.BULL_WEAKENING


def test_bull_weakening_not_triggered_when_momentum_accelerates():
    regime, _ = detect_regime(
        [],
        momentum_30d={"BTC": 12.0, "SPX": 11.0},
        previous_momentum_30d={"BTC": 6.0, "SPX": 5.0},
    )

    assert regime is MarketRegime.BULL


def test_altseason_on_falling_btc_dominance_and_alt_rally():
    assets = [
        asset("BTC.D", change_pct_24h=-2.0),
        asset("ETH", change_pct_24h=6.0),
        asset("SOL", change_pct_24h=8.0),
    ]

    regime, inputs = detect_regime(assets)

    assert regime is MarketRegime.ALTSEASON
    assert inputs["btc_dominance_change_pct"] == -2.0


def test_no_altseason_when_alts_dont_both_rally():
    assets = [
        asset("BTC.D", change_pct_24h=-2.0),
        asset("ETH", change_pct_24h=6.0),
        asset("SOL", change_pct_24h=0.5),
    ]

    regime, _ = detect_regime(assets)

    assert regime is not MarketRegime.ALTSEASON


def test_accumulation_on_long_heavy_flat_price():
    assets = [asset("BTC", change_pct_24h=0.5)]

    regime, _ = detect_regime(assets, whale_classification="long_heavy")

    assert regime is MarketRegime.ACCUMULATION


def test_distribution_on_short_heavy_flat_price():
    assets = [asset("BTC", change_pct_24h=-0.5)]

    regime, _ = detect_regime(assets, whale_classification="short_heavy")

    assert regime is MarketRegime.DISTRIBUTION


def test_no_accumulation_when_price_moved_too_much():
    assets = [asset("BTC", change_pct_24h=5.0)]

    regime, _ = detect_regime(assets, whale_classification="long_heavy")

    assert regime is not MarketRegime.ACCUMULATION


def test_recovery_when_risk_on_follows_bear():
    assets = [
        asset("SPX", change_pct_24h=1.2),
        asset("BTC", change_pct_24h=3.0),
        asset("VIX", change_pct_24h=-5.0),
        asset("DXY", change_pct_24h=-0.3),
    ]

    regime, _ = detect_regime(assets, previous_regime=MarketRegime.BEAR)

    assert regime is MarketRegime.RECOVERY


def test_recovery_does_not_fire_without_prior_bear_or_capitulation():
    assets = [
        asset("SPX", change_pct_24h=1.2),
        asset("BTC", change_pct_24h=3.0),
        asset("VIX", change_pct_24h=-5.0),
        asset("DXY", change_pct_24h=-0.3),
    ]

    regime, _ = detect_regime(assets, previous_regime=MarketRegime.RISK_ON)

    assert regime is MarketRegime.RISK_ON


def test_sideways_when_everything_is_flat():
    assets = [asset("SPX", change_pct_24h=0.1), asset("BTC", change_pct_24h=0.1)]

    regime, _ = detect_regime(assets)

    assert regime is MarketRegime.SIDEWAYS
