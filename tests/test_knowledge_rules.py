from app.services.backtest.conditions import Condition
from app.services.knowledge.rules import (
    compute_confidence_pct,
    condition_from_dict,
    condition_to_dict,
)


def test_condition_roundtrip_through_dict():
    condition = Condition(symbol="BTC", field="rsi", operator="lt", value=30.0)
    data = condition_to_dict(condition)
    restored = condition_from_dict(data)
    assert restored == condition


def test_condition_to_dict_shape():
    condition = Condition(symbol="DXY", field="return_pct", operator="lt", value=0.0)
    assert condition_to_dict(condition) == {
        "symbol": "DXY",
        "field": "return_pct",
        "operator": "lt",
        "value": 0.0,
    }


def test_confidence_scales_down_with_few_occurrences():
    # Same win rate, far fewer occurrences than the full-confidence threshold.
    low = compute_confidence_pct(win_rate_pct=80.0, occurrences=3, min_occurrences=30)
    high = compute_confidence_pct(win_rate_pct=80.0, occurrences=30, min_occurrences=30)
    assert low < high
    assert high == 80


def test_confidence_never_exceeds_win_rate():
    result = compute_confidence_pct(win_rate_pct=70.0, occurrences=1000, min_occurrences=30)
    assert result == 70
