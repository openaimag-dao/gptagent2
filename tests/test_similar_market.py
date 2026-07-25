from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.analysis.regime import MarketRegime
from app.services.similar_market.engine import _reconstruct_regime_at

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _row(return_pct: float | None, close: float = 100.0):
    return SimpleNamespace(return_pct=return_pct, close=close)


def test_reconstructs_risk_on_when_all_signals_agree():
    regime_index = {
        "SPX": {_TS: _row(0.01)},
        "BTC": {_TS: _row(0.02)},
        "VIX": {_TS: _row(-0.05)},
        "DXY": {_TS: _row(-0.01)},
        "GOLD": {_TS: _row(0.0)},
        "US10Y": {_TS: _row(0.0)},
        "FEDRATE": {_TS: _row(0.0)},
    }
    assert _reconstruct_regime_at(regime_index, _TS) == MarketRegime.RISK_ON


def test_returns_none_below_minimum_symbol_count():
    regime_index = {
        "SPX": {_TS: _row(0.01)},
        "BTC": {_TS: _row(0.02)},
        # everything else missing this timestamp
        "VIX": {},
        "DXY": {},
        "GOLD": {},
        "US10Y": {},
        "FEDRATE": {},
    }
    assert _reconstruct_regime_at(regime_index, _TS) is None


def test_missing_return_pct_excludes_that_symbol():
    regime_index = {
        "SPX": {_TS: _row(0.01)},
        "BTC": {_TS: _row(0.02)},
        "VIX": {_TS: _row(-0.05)},
        "DXY": {_TS: _row(None)},  # present but no usable value
        "GOLD": {},
        "US10Y": {},
        "FEDRATE": {},
    }
    # Only 3 usable symbols (DXY excluded) -> below the 4-symbol minimum.
    assert _reconstruct_regime_at(regime_index, _TS) is None


def test_returns_neutral_when_signals_disagree():
    regime_index = {
        "SPX": {_TS: _row(0.01)},
        "BTC": {_TS: _row(-0.02)},
        "VIX": {_TS: _row(0.03)},
        "DXY": {_TS: _row(0.01)},
        "GOLD": {},
        "US10Y": {},
        "FEDRATE": {},
    }
    assert _reconstruct_regime_at(regime_index, _TS) == MarketRegime.NEUTRAL
