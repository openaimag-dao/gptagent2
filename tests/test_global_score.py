from app.database.models import AssetClass, AssetPrice
from app.services.analysis.regime import MarketRegime
from app.services.global_score.engine import compute_global_score


def _asset(symbol: str, change_pct_24h: float | None) -> AssetPrice:
    return AssetPrice(
        symbol=symbol,
        name=symbol,
        asset_class=AssetClass.CRYPTO,
        price=100.0,
        change_pct_24h=change_pct_24h,
        source="test",
    )


def test_risk_on_regime_gives_high_risk_on_score():
    result = compute_global_score(MarketRegime.RISK_ON, {}, {}, [])
    assert result["risk_on_score"] == 85
    assert result["risk_off_score"] == 15


def test_flight_to_safety_gives_very_low_risk_on_score():
    result = compute_global_score(MarketRegime.FLIGHT_TO_SAFETY, {}, {}, [])
    assert result["risk_on_score"] == 10
    assert result["risk_off_score"] == 90


def test_missing_inputs_default_to_neutral_center():
    result = compute_global_score(MarketRegime.NEUTRAL, {}, {}, [])
    assert result["liquidity_score"] == 50
    assert result["fear_score"] == 50
    assert result["macro_pressure_score"] == 50
    assert result["institutional_activity_score"] == 50


def test_falling_fed_rate_raises_liquidity_score():
    result = compute_global_score(MarketRegime.NEUTRAL, {"fedrate_change": -0.25}, {}, [])
    assert result["liquidity_score"] > 50


def test_rising_vix_raises_fear_lowers_greed():
    result = compute_global_score(MarketRegime.NEUTRAL, {"vix_change_pct": 10.0}, {}, [])
    assert result["fear_score"] > 50
    assert result["greed_score"] < 50
    assert result["fear_score"] + result["greed_score"] == 100


def test_etf_inflow_triggered_raises_institutional_activity():
    result = compute_global_score(MarketRegime.NEUTRAL, {}, {"etf_inflow": {"triggered": True}}, [])
    assert result["institutional_activity_score"] == 75


def test_etf_inflow_not_triggered_lowers_institutional_activity():
    result = compute_global_score(
        MarketRegime.NEUTRAL, {}, {"etf_inflow": {"triggered": False}}, []
    )
    assert result["institutional_activity_score"] == 25


def test_strong_crypto_gains_raise_crypto_strength():
    assets = [_asset("BTC", 5.0), _asset("ETH", 6.0), _asset("SOL", 7.0)]
    result = compute_global_score(MarketRegime.NEUTRAL, {}, {}, assets)
    assert result["crypto_strength_score"] > 50


def test_global_score_is_bounded_0_to_100():
    assets = [_asset("BTC", 50.0)]
    inputs = {"fedrate_change": -5.0, "vix_change_pct": -50.0, "dxy_change_pct": -20.0}
    result = compute_global_score(MarketRegime.RISK_ON, inputs, {}, assets)
    assert 0 <= result["global_score"] <= 100


def test_trend_strength_none_without_momentum_data():
    result = compute_global_score(MarketRegime.NEUTRAL, {}, {}, [])
    assert result["trend_strength_score"] is None


def test_trend_strength_high_on_strong_momentum():
    result = compute_global_score(
        MarketRegime.NEUTRAL, {"momentum_30d": {"BTC": 20.0, "SPX": 18.0}}, {}, []
    )
    assert result["trend_strength_score"] > 50


def test_risk_score_blends_risk_off_fear_and_macro_pressure():
    result = compute_global_score(
        MarketRegime.RISK_OFF, {"vix_change_pct": 20.0, "dxy_change_pct": 5.0}, {}, []
    )
    assert result["risk_score"] > 50


def test_confidence_score_passes_through_signal_confidence():
    result = compute_global_score(MarketRegime.NEUTRAL, {}, {}, [], confidence_pct=72)
    assert result["confidence_score"] == 72


def test_confidence_score_none_when_not_given():
    result = compute_global_score(MarketRegime.NEUTRAL, {}, {}, [])
    assert result["confidence_score"] is None
