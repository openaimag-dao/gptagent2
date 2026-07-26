from app.services.ranking.factors import FACTOR_CONDITIONS, edge_pct


def test_edge_pct_none_when_metrics_missing():
    assert edge_pct(None) is None


def test_edge_pct_none_when_win_rate_missing():
    assert edge_pct({"win_rate_pct": None}) is None


def test_edge_pct_above_coin_flip():
    assert edge_pct({"win_rate_pct": 65.0}) == 15.0


def test_edge_pct_below_coin_flip():
    assert edge_pct({"win_rate_pct": 35.0}) == 15.0


def test_edge_pct_zero_at_exactly_fifty():
    assert edge_pct({"win_rate_pct": 50.0}) == 0.0


def test_factor_conditions_cover_signal_engine_factors_except_etf_inflow():
    assert set(FACTOR_CONDITIONS) == {
        "nasdaq_up",
        "dxy_down",
        "gold_up",
        "fed_dovish",
        "vix_up",
        "us10y_up",
    }
