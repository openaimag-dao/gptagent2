from app.services.analysis.regime import MarketRegime
from app.services.whatif.scenarios import (
    SHOCKS,
    SHOCKS_BY_KEY,
    average_forward_return,
    correlation_direction,
)

_VALID_DIRECTIONS = {"up", "down", "unchanged"}
_VALID_REGIME_VALUES = {regime.value for regime in MarketRegime}


def test_every_shock_key_is_unique():
    keys = [shock.key for shock in SHOCKS]
    assert len(keys) == len(set(keys))


def test_every_shock_regime_shift_is_a_real_market_regime_value():
    for shock in SHOCKS:
        assert shock.regime_shift_toward in _VALID_REGIME_VALUES, shock.key


def test_every_shock_risk_and_liquidity_direction_is_valid():
    for shock in SHOCKS:
        assert shock.risk_direction in _VALID_DIRECTIONS, shock.key
        assert shock.liquidity_direction in _VALID_DIRECTIONS, shock.key


def test_shocks_by_key_matches_shocks_tuple():
    assert set(SHOCKS_BY_KEY) == {shock.key for shock in SHOCKS}
    for key, shock in SHOCKS_BY_KEY.items():
        assert shock.key == key


def test_average_forward_return_computes_mean_of_available_values():
    occurrences = [
        {"return_7d_pct": 5.0},
        {"return_7d_pct": 3.0},
        {"return_7d_pct": None},
    ]

    avg, sample_size = average_forward_return(occurrences)

    assert avg == 4.0
    assert sample_size == 2


def test_average_forward_return_none_when_nothing_available():
    occurrences = [{"return_7d_pct": None}, {"return_7d_pct": None}]

    avg, sample_size = average_forward_return(occurrences)

    assert avg is None
    assert sample_size == 0


def test_average_forward_return_empty_list():
    avg, sample_size = average_forward_return([])

    assert avg is None
    assert sample_size == 0


def test_average_forward_return_uses_specified_key():
    occurrences = [{"return_24h_pct": 2.0, "return_7d_pct": 10.0}]

    avg, sample_size = average_forward_return(occurrences, key="return_24h_pct")

    assert avg == 2.0
    assert sample_size == 1


def test_correlation_direction_none_when_correlation_missing():
    assert correlation_direction(None, shock_sign=1) is None


def test_correlation_direction_none_when_shock_sign_is_zero():
    assert correlation_direction(-0.5, shock_sign=0) is None


def test_correlation_direction_bullish_when_net_positive():
    # DXY drops (shock_sign=-1), BTC-DXY correlation is negative -> net positive -> bullish
    assert correlation_direction(-0.4, shock_sign=-1) == "bullish"


def test_correlation_direction_bearish_when_net_negative():
    # Nasdaq crashes (shock_sign=-1), BTC-NASDAQ correlation is positive -> net negative -> bearish
    assert correlation_direction(0.4, shock_sign=-1) == "bearish"


def test_correlation_direction_neutral_when_weak():
    assert correlation_direction(0.05, shock_sign=1) == "neutral"
