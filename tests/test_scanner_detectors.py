from app.services.scanner.detectors import (
    classify_price_event,
    detect_flash_move,
    detect_new_high_low,
    detect_range_breakout,
    detect_sector_ecosystem_event,
    detect_support_resistance_break,
    detect_trend_change,
    detect_volatility_regime,
    detect_volume_multiple,
    price_ladder_for,
)


def test_price_ladder_for_default_and_override():
    assert price_ladder_for("BTC") == (3.0, 5.0, 8.0, 10.0)


def test_classify_price_event_none_below_info():
    assert classify_price_event("BTC", 1.0) is None
    assert classify_price_event("BTC", None) is None


def test_classify_price_event_picks_highest_tier():
    result = classify_price_event("BTC", 9.0)
    assert result == {"symbol": "BTC", "direction": "up", "pct_change": 9.0, "tier": "high"}


def test_classify_price_event_direction_down():
    result = classify_price_event("BTC", -6.0)
    assert result["direction"] == "down"
    assert result["tier"] == "important"


def test_price_ladder_for_unscaled_without_volatility():
    assert price_ladder_for("BTC", realized_volatility_pct=None) == (3.0, 5.0, 8.0, 10.0)
    assert price_ladder_for("BTC", realized_volatility_pct=0.0) == (3.0, 5.0, 8.0, 10.0)


def test_price_ladder_for_scales_up_for_a_more_volatile_symbol():
    # reference is 2.0%; 6.0% realized vol -> 3x ratio, clamped to max 2.5x
    ladder = price_ladder_for(
        "SMALLCAP", realized_volatility_pct=6.0, min_multiplier=0.5, max_multiplier=2.5
    )
    assert ladder == (7.5, 12.5, 20.0, 25.0)


def test_price_ladder_for_scales_down_for_a_quieter_symbol():
    # 0.2% realized vol -> 0.1x ratio, clamped to min 0.5x
    ladder = price_ladder_for(
        "STABLE", realized_volatility_pct=0.2, min_multiplier=0.5, max_multiplier=2.5
    )
    assert ladder == (1.5, 2.5, 4.0, 5.0)


def test_classify_price_event_uses_volatility_scaled_ladder():
    # 3.0% move would be "info" on the flat ladder, but on a highly
    # volatile symbol (6% realized vol -> 2.5x-capped ladder starting at
    # 7.5%) it doesn't even clear "info".
    assert (
        classify_price_event(
            "SMALLCAP", 3.0, realized_volatility_pct=6.0, min_multiplier=0.5, max_multiplier=2.5
        )
        is None
    )


def test_detect_volume_multiple_thresholds():
    assert detect_volume_multiple(None, 100.0) is None
    assert detect_volume_multiple(100.0, None) is None
    assert detect_volume_multiple(100.0, 100.0) is None  # 1x, below the 2x floor
    assert detect_volume_multiple(250.0, 100.0) == {"label": "Volume x2", "multiple": 2.5}
    assert detect_volume_multiple(1200.0, 100.0) == {"label": "Volume x10", "multiple": 12.0}


def test_detect_flash_move():
    assert detect_flash_move(None) is None
    assert detect_flash_move(-3.0) is None
    assert detect_flash_move(-9.0) == "Flash Crash"
    assert detect_flash_move(9.0) == "Flash Rally"


def test_detect_volatility_regime():
    assert detect_volatility_regime(None, 10.0) is None
    assert detect_volatility_regime(10.0, None) is None
    assert detect_volatility_regime(30.0, 10.0) == "Abnormal Volatility"
    assert detect_volatility_regime(19.0, 10.0) == "Volatility Expansion"
    assert detect_volatility_regime(3.0, 10.0) == "Low Volatility Compression"
    assert detect_volatility_regime(10.0, 10.0) is None


def test_detect_new_high_low():
    assert detect_new_high_low(110.0, 100.0, 90.0) == "New Daily High"
    assert detect_new_high_low(80.0, 100.0, 90.0) == "New Daily Low"
    assert detect_new_high_low(95.0, 100.0, 90.0) is None


def test_detect_range_breakout():
    assert detect_range_breakout(110.0, 100.0, 90.0, "Weekly Breakout") == "Weekly Breakout (Up)"
    assert detect_range_breakout(80.0, 100.0, 90.0, "Monthly Breakout") == "Monthly Breakout (Down)"
    assert detect_range_breakout(95.0, 100.0, 90.0, "Weekly Breakout") is None


def test_detect_support_resistance_break():
    assert detect_support_resistance_break(110.0, 90.0, 100.0) == "Resistance Break"
    assert detect_support_resistance_break(80.0, 90.0, 100.0) == "Support Break"
    assert detect_support_resistance_break(95.0, 90.0, 100.0) is None


def test_detect_trend_change():
    assert detect_trend_change(None, 60.0) is None
    assert detect_trend_change(50.0, 65.0) == "Trend Acceleration"
    assert detect_trend_change(65.0, 50.0) == "Trend Weakening"
    assert detect_trend_change(50.0, 55.0) is None


def test_detect_sector_ecosystem_event_requires_threshold_and_corroboration():
    assert detect_sector_ecosystem_event("AI", 2.0, []) is None  # below threshold
    assert detect_sector_ecosystem_event("AI", 6.0, [None, None]) is None  # no corroboration
    # A single mover cannot "corroborate itself" -- needs >= 2 independent
    # movers, matching the mission's own multi-signal worked example.
    single_mover = [{"symbol": "FET", "direction": "up", "pct_change": 6.0, "tier": "important"}]
    assert detect_sector_ecosystem_event("AI", 6.0, single_mover) is None

    member_events = [
        {"symbol": "FET", "direction": "up", "pct_change": 6.0, "tier": "important"},
        {"symbol": "AGIX", "direction": "up", "pct_change": 7.0, "tier": "important"},
        None,
    ]
    event = detect_sector_ecosystem_event("AI", 6.0, member_events)
    assert event["title"] == "AI ECOSYSTEM STRENGTHENING"
    assert event["corroborating_symbols"] == ["FET", "AGIX"]


def test_detect_sector_ecosystem_event_weakening_direction():
    member_events = [
        {"symbol": "FET", "direction": "down", "pct_change": -6.0, "tier": "important"},
        {"symbol": "AGIX", "direction": "down", "pct_change": -7.0, "tier": "important"},
    ]
    event = detect_sector_ecosystem_event("AI", -6.0, member_events)
    assert event["title"] == "AI ECOSYSTEM WEAKENING"
    assert event["direction"] == "down"
