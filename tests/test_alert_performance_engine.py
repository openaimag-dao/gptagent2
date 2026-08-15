from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.alert_performance.engine import (
    compute_baseline_return_pct,
    compute_excursions,
    grade_alert_outcome,
    grade_alert_performance,
    resolve_alert_direction,
    resolve_alert_symbol,
    summarize_alert_performance,
    summarize_alert_performance_by_type,
)


def _row(timestamp, close, high=None, low=None, return_pct=None):
    return SimpleNamespace(
        timestamp=timestamp,
        close=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        return_pct=return_pct,
    )


def _alert_log(id, alert_type, data, triggered_at):
    return SimpleNamespace(id=id, alert_type=alert_type, data=data, triggered_at=triggered_at)


def _grade(
    alert_type,
    significant_move,
    direction_continued,
    realized_move_pct=1.0,
    edge_vs_baseline_pct=None,
):
    return SimpleNamespace(
        alert_type=alert_type,
        significant_move=significant_move,
        direction_continued=direction_continued,
        realized_move_pct=realized_move_pct,
        edge_vs_baseline_pct=edge_vs_baseline_pct,
    )


# ---- resolve_alert_symbol ----


def test_resolve_alert_symbol_from_symbols_list():
    assert resolve_alert_symbol({"symbols": ["eth", "btc"]}) == "ETH"


def test_resolve_alert_symbol_from_singular_symbol():
    assert resolve_alert_symbol({"symbol": "btc"}) == "BTC"


def test_resolve_alert_symbol_from_readings_list():
    assert resolve_alert_symbol({"readings": [{"symbol": "sol"}]}) == "SOL"


def test_resolve_alert_symbol_from_moves_list():
    assert resolve_alert_symbol({"moves": [{"symbol": "doge"}]}) == "DOGE"


def test_resolve_alert_symbol_none_when_unresolvable():
    assert resolve_alert_symbol({"tags": ["ai"], "sector": "Layer 1"}) is None
    assert resolve_alert_symbol({}) is None
    assert resolve_alert_symbol(None) is None


# ---- resolve_alert_direction ----


def test_resolve_alert_direction_from_direction_field():
    assert resolve_alert_direction({"direction": "up"}) == "up"
    assert resolve_alert_direction({"direction": "bearish"}) == "down"


def test_resolve_alert_direction_from_pct_change_sign():
    assert resolve_alert_direction({"pct_change": 4.2}) == "up"
    assert resolve_alert_direction({"pct_change": -1.1}) == "down"


def test_resolve_alert_direction_none_when_no_claim():
    assert resolve_alert_direction({"multiple": 3.0, "label": "Volume x3"}) is None
    assert resolve_alert_direction({}) is None


# ---- grade_alert_outcome ----


def test_grade_alert_outcome_significant_and_direction_continued():
    outcome = grade_alert_outcome(100.0, 105.0, "up", significant_move_pct=3.0)
    assert outcome["realized_move_pct"] == 5.0
    assert outcome["significant_move"] is True
    assert outcome["direction_continued"] is True


def test_grade_alert_outcome_direction_reversed():
    outcome = grade_alert_outcome(100.0, 95.0, "up", significant_move_pct=3.0)
    assert outcome["direction_continued"] is False


def test_grade_alert_outcome_not_significant():
    outcome = grade_alert_outcome(100.0, 101.0, "up", significant_move_pct=3.0)
    assert outcome["significant_move"] is False


def test_grade_alert_outcome_no_implied_direction_leaves_it_none():
    outcome = grade_alert_outcome(100.0, 90.0, None, significant_move_pct=3.0)
    assert outcome["direction_continued"] is None
    assert outcome["significant_move"] is True


# ---- POST-V9 Phase 10: compute_excursions ----


def test_compute_excursions_up_direction_uses_real_intrabar_high_low():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    window = [
        _row(t0, 100.0, high=101.0, low=99.0),
        _row(t0 + timedelta(days=1), 103.0, high=106.0, low=102.0),
        _row(t0 + timedelta(days=2), 101.0, high=104.0, low=95.0),
    ]
    result = compute_excursions(100.0, window, implied_direction="up")
    # Highest high across the window is 106 -> +6%; lowest low is 95 -> -5%.
    assert result["max_favorable_excursion_pct"] == 6.0
    assert result["max_adverse_excursion_pct"] == -5.0
    assert result["peak_move_pct"] == 6.0
    assert result["time_to_peak_days"] == 1


def test_compute_excursions_down_direction_swaps_favorable_and_adverse():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    window = [
        _row(t0, 100.0, high=101.0, low=99.0),
        _row(t0 + timedelta(days=1), 103.0, high=106.0, low=102.0),
        _row(t0 + timedelta(days=2), 101.0, high=104.0, low=95.0),
    ]
    result = compute_excursions(100.0, window, implied_direction="down")
    # For a bearish thesis, the favorable side is the drop to 95 (-5%);
    # the adverse side is the rally to 106 (+6%).
    assert result["max_favorable_excursion_pct"] == -5.0
    assert result["max_adverse_excursion_pct"] == 6.0
    # peak_move_pct/time_to_peak are direction-agnostic -- unchanged.
    assert result["peak_move_pct"] == 6.0


def test_compute_excursions_no_implied_direction_still_reports_peak():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    window = [_row(t0, 100.0, high=110.0, low=98.0)]
    result = compute_excursions(100.0, window, implied_direction=None)
    assert result["max_favorable_excursion_pct"] is None
    assert result["max_adverse_excursion_pct"] is None
    assert result["peak_move_pct"] == 10.0
    assert result["time_to_peak_days"] == 0


def test_compute_excursions_empty_window_or_zero_reference_is_all_none():
    assert compute_excursions(100.0, [], "up") == {
        "max_favorable_excursion_pct": None,
        "max_adverse_excursion_pct": None,
        "peak_move_pct": None,
        "time_to_peak_days": None,
    }
    window = [_row(datetime(2026, 1, 1, tzinfo=UTC), 100.0)]
    assert compute_excursions(0.0, window, "up")["peak_move_pct"] is None


# ---- POST-V9 Phase 10: compute_baseline_return_pct ----


def test_compute_baseline_return_pct_averages_prior_complete_windows():
    # returns_series: index 0..5. horizon=1 forward returns:
    # fwd[0]=returns[1]=0.02, fwd[1]=returns[2]=-0.01, fwd[2]=returns[3]=0.03,
    # fwd[3]=returns[4]=0.01, fwd[4]=returns[5]=0.04.
    returns_series = [0.05, 0.02, -0.01, 0.03, 0.01, 0.04]
    # reference_idx=4: windows whose data is fully realized at or before
    # the reference candle (i + horizon_days <= reference_idx) are
    # fwd[0..3] -- fwd[3]'s window ends exactly AT the reference candle
    # (its own known return_pct), which is data available at alert time,
    # not future data, so it's honestly included.
    baseline = compute_baseline_return_pct(returns_series, reference_idx=4, horizon_days=1)
    assert baseline == round(100 * (0.02 - 0.01 + 0.03 + 0.01) / 4, 4)


def test_compute_baseline_return_pct_never_uses_data_at_or_after_reference():
    # A single, deliberately extreme return placed AT the reference index
    # (and beyond) must never leak into the baseline average.
    returns_series = [0.01, 0.01, 0.01, 999.0, 999.0]
    baseline_before_extreme = compute_baseline_return_pct(
        returns_series, reference_idx=2, horizon_days=1
    )
    # Only fwd[0]=returns[1]=0.01 completes before reference_idx=2 -- the
    # 999.0 values at/after the reference must not appear.
    assert baseline_before_extreme == 1.0


def test_compute_baseline_return_pct_none_without_enough_prior_history():
    assert compute_baseline_return_pct([0.05], reference_idx=0, horizon_days=1) is None
    assert compute_baseline_return_pct([], reference_idx=5, horizon_days=1) is None


# ---- grade_alert_performance ----


async def test_grade_alert_performance_grades_a_gradable_alert():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    log = _alert_log(1, "scanner:price_event", {"symbol": "BTC", "direction": "up"}, t0)
    rows = [
        _row(t0, 100.0),
        _row(t0 + timedelta(days=1), 102.0),
        _row(t0 + timedelta(days=3), 108.0),
    ]

    grade_session = AsyncMock()
    grade_session.scalars.side_effect = [iter([]), iter([log])]
    grade_session.__aenter__.return_value = grade_session
    write_session = AsyncMock()
    write_session.add = MagicMock()
    write_session.__aenter__.return_value = write_session
    session_factory = MagicMock(side_effect=[grade_session, write_session])

    config = SimpleNamespace(symbol="BTC", model=object())
    with (
        patch("app.services.alert_performance.engine.find_symbol_config", return_value=config),
        patch("app.services.alert_performance.engine.get_series", AsyncMock(return_value=rows)),
    ):
        graded = await grade_alert_performance(session_factory)

    assert graded == 1
    write_session.add.assert_called_once()
    (added_row,), _ = write_session.add.call_args
    assert added_row.alert_log_id == 1
    assert added_row.symbol == "BTC"
    assert added_row.realized_move_pct == 8.0
    assert added_row.significant_move is True
    assert added_row.direction_continued is True
    # POST-V9 Phase 10: excursions computed from the same close-as-high/low
    # rows (no real intrabar range in this fixture); no prior history
    # before the reference candle, so baseline honestly stays None.
    assert added_row.max_favorable_excursion_pct == 8.0
    assert added_row.max_adverse_excursion_pct == 0.0
    assert added_row.peak_move_pct == 8.0
    assert added_row.time_to_peak_days == 3
    assert added_row.baseline_return_pct is None
    assert added_row.edge_vs_baseline_pct is None


async def test_grade_alert_performance_skips_unresolvable_symbol():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    log = _alert_log(2, "scanner:sector_ecosystem", {"tags": ["ai"]}, t0)

    grade_session = AsyncMock()
    grade_session.scalars.side_effect = [iter([]), iter([log])]
    grade_session.__aenter__.return_value = grade_session
    write_session = AsyncMock()
    write_session.add = MagicMock()
    write_session.__aenter__.return_value = write_session
    session_factory = MagicMock(side_effect=[grade_session, write_session])

    graded = await grade_alert_performance(session_factory)

    assert graded == 0
    write_session.add.assert_not_called()


async def test_grade_alert_performance_skips_symbol_with_no_history_registry_entry():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    log = _alert_log(3, "alert:price", {"symbol": "UNKNOWNCOIN"}, t0)

    grade_session = AsyncMock()
    grade_session.scalars.side_effect = [iter([]), iter([log])]
    grade_session.__aenter__.return_value = grade_session
    write_session = AsyncMock()
    write_session.add = MagicMock()
    write_session.__aenter__.return_value = write_session
    session_factory = MagicMock(side_effect=[grade_session, write_session])

    with patch("app.services.alert_performance.engine.find_symbol_config", return_value=None):
        graded = await grade_alert_performance(session_factory)

    assert graded == 0
    write_session.add.assert_not_called()


async def test_grade_alert_performance_skips_when_horizon_not_elapsed():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    log = _alert_log(4, "scanner:price_event", {"symbol": "BTC"}, t0)
    rows = [_row(t0, 100.0)]  # nothing after -- horizon not elapsed

    grade_session = AsyncMock()
    grade_session.scalars.side_effect = [iter([]), iter([log])]
    grade_session.__aenter__.return_value = grade_session
    write_session = AsyncMock()
    write_session.add = MagicMock()
    write_session.__aenter__.return_value = write_session
    session_factory = MagicMock(side_effect=[grade_session, write_session])

    config = SimpleNamespace(symbol="BTC", model=object())
    with (
        patch("app.services.alert_performance.engine.find_symbol_config", return_value=config),
        patch("app.services.alert_performance.engine.get_series", AsyncMock(return_value=rows)),
    ):
        graded = await grade_alert_performance(session_factory)

    assert graded == 0
    write_session.add.assert_not_called()


async def test_grade_alert_performance_no_candidates_returns_zero_without_touching_write_session():
    grade_session = AsyncMock()
    grade_session.scalars.side_effect = [iter([]), iter([])]
    grade_session.__aenter__.return_value = grade_session
    session_factory = MagicMock(return_value=grade_session)

    graded = await grade_alert_performance(session_factory)

    assert graded == 0


# ---- summarize_alert_performance / summarize_alert_performance_by_type ----


async def test_summarize_alert_performance_empty_returns_none_fields():
    session = AsyncMock()
    session.scalars.return_value = iter([])
    session.__aenter__.return_value = session
    session_factory = MagicMock(return_value=session)

    summary = await summarize_alert_performance(session_factory)

    assert summary["graded_count"] == 0
    assert summary["significant_move_rate_pct"] is None
    assert summary["direction_continued_rate_pct"] is None
    assert summary["avg_edge_vs_baseline_pct"] is None
    assert summary["edge_vs_baseline_sample_count"] == 0


async def test_summarize_alert_performance_computes_rates():
    grades = [
        _grade("scanner:price_event", True, True, edge_vs_baseline_pct=2.0),
        _grade("scanner:price_event", True, False, edge_vs_baseline_pct=4.0),
        _grade("scanner:price_event", False, None),  # no baseline available
    ]
    session = AsyncMock()
    session.scalars.return_value = iter(grades)
    session.__aenter__.return_value = session
    session_factory = MagicMock(return_value=session)

    summary = await summarize_alert_performance(session_factory)

    assert summary["graded_count"] == 3
    assert summary["significant_move_rate_pct"] == round(100 * 2 / 3, 1)
    assert summary["directional_alerts_count"] == 2
    assert summary["direction_continued_rate_pct"] == 50.0
    # POST-V9 Phase 11: only averaged over rows that actually have a
    # baseline -- the third grade (no edge_vs_baseline_pct) is excluded
    # from both the average and its own sample count.
    assert summary["avg_edge_vs_baseline_pct"] == 3.0
    assert summary["edge_vs_baseline_sample_count"] == 2


async def test_summarize_alert_performance_by_type_groups_and_sorts():
    grades = [
        _grade("scanner:price_event", True, True),
        _grade("scanner:price_event", True, True),
        _grade("critical_shock:price_shock", False, None),
    ]
    session = AsyncMock()
    session.scalars.return_value = iter(grades)
    session.__aenter__.return_value = session
    session_factory = MagicMock(return_value=session)

    by_type = await summarize_alert_performance_by_type(session_factory)

    assert by_type[0]["alert_type"] == "scanner:price_event"
    assert by_type[0]["graded_count"] == 2
    assert by_type[1]["alert_type"] == "critical_shock:price_shock"
    assert by_type[1]["graded_count"] == 1
