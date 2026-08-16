from unittest.mock import AsyncMock

from pydantic import ValidationError

from app.database.models import (
    AssetClass,
    AssetPrice,
    MarketRegimeSnapshot,
    NewsCategory,
    NewsItem,
    NewsSentiment,
    Report,
    SignalSnapshot,
)
from app.services.analysis.regime import MarketRegime
from app.services.analysis.report import (
    ReportGenerator,
    _format_data_quality_note,
    _format_replay_comparison,
    _format_watchdog_citation,
    build_institutional_report,
    build_user_prompt,
    derive_risk_level,
    recover_analysis_fields,
    strip_json_fence,
    watchdog_report_input,
)
from app.services.analysis.schemas import AIAnalysisContent
from app.services.reliability.engine import AgentReliabilityEngine


def _report_generator(reliability_engine=None):
    return ReportGenerator(
        session_factory=AsyncMock(),
        market_repository=AsyncMock(),
        news_repository=AsyncMock(),
        correlation_engine=AsyncMock(),
        regime_detector=AsyncMock(),
        signal_engine=AsyncMock(),
        agent_orchestrator=AsyncMock(),
        reliability_engine=reliability_engine or AsyncMock(),
    )


def test_derive_risk_level_high_for_risk_off():
    assert derive_risk_level(MarketRegime.RISK_OFF) == "high"
    assert derive_risk_level(MarketRegime.FLIGHT_TO_SAFETY) == "high"


def test_derive_risk_level_low_for_risk_on():
    assert derive_risk_level(MarketRegime.RISK_ON) == "low"


def test_derive_risk_level_moderate_otherwise():
    assert derive_risk_level(MarketRegime.NEUTRAL) == "moderate"


def test_strip_json_fence_removes_json_fence_with_language_tag():
    assert strip_json_fence('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_json_fence_removes_bare_fence():
    assert strip_json_fence('```\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_json_fence_handles_truncated_response_with_no_closing_fence():
    assert strip_json_fence('```json\n{"a": 1, "b": "unterm') == '{"a": 1, "b": "unterm'


def test_strip_json_fence_leaves_unfenced_content_unchanged():
    assert strip_json_fence('{"a": 1}') == '{"a": 1}'


def test_strip_json_fence_leaves_bare_fence_marker_unchanged():
    assert strip_json_fence("```") == "```"


def _asset(symbol: str, price: float, change_pct_24h: float | None) -> AssetPrice:
    return AssetPrice(
        symbol=symbol,
        name=symbol,
        asset_class=AssetClass.CRYPTO,
        price=price,
        change_pct_24h=change_pct_24h,
        source="test",
    )


def test_build_user_prompt_includes_all_sections_and_handles_missing_data():
    assets = [_asset("BTC", 65000.0, 2.5)]
    news = [
        NewsItem(
            source="coindesk",
            category=NewsCategory.CRYPTO,
            title="Bitcoin rallies",
            url="https://example.com/1",
            sentiment=NewsSentiment.BULLISH,
            sentiment_score=2.0,
        )
    ]
    regime_snapshot = MarketRegimeSnapshot(
        regime=MarketRegime.RISK_ON, inputs={"btc_change_pct": 2.5}
    )
    signal_snapshot = SignalSnapshot(
        bull_score=5, bear_score=0, net_score=5, confidence_pct=100, factors={}
    )

    prompt = build_user_prompt(assets, news, [], regime_snapshot, signal_snapshot)

    assert "MARKET SNAPSHOT" in prompt
    assert "BTC: 65,000.00" in prompt
    assert "NASDAQ: not available" in prompt
    assert "DETECTED MARKET REGIME" in prompt
    assert "risk_on" in prompt
    assert "BULL/BEAR SIGNAL SCORE" in prompt
    assert "Bull score: 5" in prompt
    assert "ROLLING CORRELATIONS" in prompt
    assert "No correlation data available yet." in prompt
    assert "HISTORICAL ANALOGS" in prompt
    assert "Historical analog data unavailable." in prompt
    assert "RECENT NEWS" in prompt
    assert "Bitcoin rallies" in prompt
    assert "MULTI-AGENT SUMMARIES" in prompt
    assert "Not yet computed." in prompt


def test_build_user_prompt_includes_agent_summaries_when_provided():
    from app.services.agents.base import AgentOutput

    assets = [_asset("BTC", 65000.0, 2.5)]
    regime_snapshot = MarketRegimeSnapshot(
        regime=MarketRegime.RISK_ON, inputs={"btc_change_pct": 2.5}
    )
    signal_snapshot = SignalSnapshot(
        bull_score=5, bear_score=0, net_score=5, confidence_pct=100, factors={}
    )
    agent_outputs = {
        "macro": AgentOutput(agent="macro", summary="*MACRO SUMMARY*\n\nDXY down."),
    }

    prompt = build_user_prompt(
        assets, [], [], regime_snapshot, signal_snapshot, agent_outputs=agent_outputs
    )

    assert "DXY down." in prompt


def _scenario(key: str, name: str, probability_pct: int, rationale: str = "reason") -> dict:
    return {"key": key, "name": name, "probability_pct": probability_pct, "rationale": rationale}


def _report(**overrides) -> Report:
    defaults = {
        "report_type": "scheduled",
        "regime": "risk_on",
        "risk_level": "low",
        "bull_score": 5,
        "bear_score": 1,
        "confidence_pct": 80,
        "analysis": {
            "what_changed": "BTC broke above 65k.",
            "who_is_driving": "Spot ETF inflows.",
            "macro_explanation": "DXY weakening.",
            "historical_comparison": "Similar to March 2024.",
            "main_risks": "Overleveraged futures market.",
            "institutional_behavior": "Whale accumulation observed.",
            "actionable_insights": "Consider scaling into strength.",
            "key_events_today": "FOMC minutes at 14:00 ET.",
            "probability_bullish_pct": 60,
            "probability_bearish_pct": 20,
            "probability_neutral_pct": 20,
        },
        "institutional_summary": {
            "scenarios": [
                _scenario("soft_landing", "Soft Landing", 55),
                _scenario("risk_off", "Risk Off", 20),
                _scenario("liquidity_expansion", "Liquidity Expansion", 15),
                _scenario("black_swan", "Black Swan", 10),
            ]
        },
    }
    defaults.update(overrides)
    return Report(**defaults)


def test_build_institutional_report_composes_from_analysis_and_scenarios():
    report = _report()
    sector_breadth = [
        {"sector": "Layer 1", "avg_change_pct_24h": 5.0, "coin_count": 3},
        {"sector": "Meme", "avg_change_pct_24h": 2.0, "coin_count": 5},
        {"sector": "DeFi", "avg_change_pct_24h": -1.0, "coin_count": 4},
        {"sector": "Gaming", "avg_change_pct_24h": -4.0, "coin_count": 2},
    ]

    ir = build_institutional_report(report, sector_breadth)

    assert ir["executive_summary"] == "BTC broke above 65k."
    assert "Soft Landing" in ir["biggest_opportunity"]
    assert "Risk Off" in ir["biggest_risk"]
    assert "Spot ETF inflows." in ir["market_drivers"]
    assert "DXY weakening." in ir["market_drivers"]
    assert "Layer 1" in ir["sector_rotation"]
    assert "Leading:" in ir["sector_rotation"]
    assert "Lagging:" in ir["sector_rotation"]
    assert ir["historical_comparison"] == "Similar to March 2024."
    assert ir["ai_conclusion"] == "Consider scaling into strength."
    assert ir["what_to_watch_next"] == "FOMC minutes at 14:00 ET."
    assert ir["main_risks"] == "Overleveraged futures market."
    assert ir["institutional_behavior"] == "Whale accumulation observed."
    # No global_score in institutional_summary -- honestly None, not fabricated.
    assert ir["risk_detail"] is None


def test_build_institutional_report_surfaces_risk_detail_from_global_score():
    report = _report(
        institutional_summary={
            "scenarios": [],
            "global_score": {
                "risk_on_score": 65,
                "risk_off_score": 35,
                "liquidity_score": 70,
                "macro_pressure_score": 50,
            },
        }
    )

    ir = build_institutional_report(report, sector_breadth=None)

    assert ir["risk_detail"] == "Risk-On 65 / Risk-Off 35 | Liquidity 70 | Macro pressure 50"


def test_build_institutional_report_is_honest_when_scenarios_and_breadth_are_missing():
    report = _report(institutional_summary={})

    ir = build_institutional_report(report, sector_breadth=None)

    assert ir["biggest_opportunity"] == "No bullish scenario currently dominant."
    assert ir["biggest_risk"] == "No bearish scenario currently dominant."
    assert "unavailable" in ir["sector_rotation"]


def _diff(regime_changed=False, health_delta=None, risk_delta=None):
    return {
        "regime": {
            "from": "bull",
            "to": "bear" if regime_changed else "bull",
            "changed": regime_changed,
        },
        "health_score": {"from": 60, "to": 60 + (health_delta or 0), "delta": health_delta},
        "risk_score": {"from": 40, "to": 40 + (risk_delta or 0), "delta": risk_delta},
    }


def test_format_replay_comparison_returns_none_without_data():
    assert _format_replay_comparison(None) is None


def test_format_replay_comparison_reports_regime_and_score_changes():
    comparison = {"hours_ago": 24, "diff": _diff(regime_changed=True, health_delta=-10)}

    text = _format_replay_comparison(comparison)

    assert "Vs. 24h ago (Replay):" in text
    assert "regime shifted bull -> bear" in text
    assert "health -10" in text


def test_format_replay_comparison_reports_no_material_change():
    comparison = {"hours_ago": 24, "diff": _diff()}

    text = _format_replay_comparison(comparison)

    assert text == "No material change vs. 24h ago (Replay)."


def test_build_institutional_report_appends_replay_comparison_to_historical_comparison():
    report = _report()
    replay_comparison = {"hours_ago": 24, "diff": _diff(regime_changed=True, risk_delta=5)}

    ir = build_institutional_report(
        report, sector_breadth=None, replay_comparison=replay_comparison
    )

    assert ir["historical_comparison"].startswith("Similar to March 2024.")
    assert (
        "Vs. 24h ago (Replay): regime shifted bull -> bear; risk +5." in ir["historical_comparison"]
    )


def test_watchdog_report_input_returns_none_without_a_snapshot():
    assert watchdog_report_input(None) is None


def test_watchdog_report_input_shapes_only_the_needed_fields():
    snapshot = type(
        "FakeWatchdogSnapshot",
        (),
        {
            "market_health": "Watch",
            "committee_recommendation": "SELL (moderate conviction)",
            "highest_risk": "Macro liquidity tightening",
        },
    )()

    result = watchdog_report_input(snapshot)

    assert result == {
        "market_health": "Watch",
        "committee_recommendation": "SELL (moderate conviction)",
    }


def test_format_watchdog_citation_returns_none_without_data():
    assert _format_watchdog_citation(None) is None
    assert _format_watchdog_citation({"market_health": "Watch"}) is None


def test_format_watchdog_citation_cites_market_health_and_committee():
    watchdog = {"market_health": "Watch", "committee_recommendation": "SELL (moderate conviction)"}

    text = _format_watchdog_citation(watchdog)

    assert text == (
        "Watchdog's last cycle reads Watch -- Investment Committee: SELL (moderate conviction)."
    )


def test_build_institutional_report_includes_watchdog_note():
    report = _report()
    watchdog = {"market_health": "Watch", "committee_recommendation": "SELL (moderate conviction)"}

    ir = build_institutional_report(report, sector_breadth=None, watchdog=watchdog)

    assert ir["watchdog_note"] == (
        "Watchdog's last cycle reads Watch -- Investment Committee: SELL (moderate conviction)."
    )


def test_build_institutional_report_is_honest_when_watchdog_is_missing():
    report = _report()

    ir = build_institutional_report(report, sector_breadth=None, watchdog=None)

    assert ir["watchdog_note"] is None


def _valid_analysis_payload(**overrides) -> dict:
    payload = {
        "what_changed": "BTC broke above 65k.",
        "why": "ETF inflows accelerated.",
        "who_is_driving": "Spot ETF inflows.",
        "institutional_behavior": "Whale accumulation observed.",
        "macro_explanation": "DXY weakening.",
        "historical_comparison": "Similar to March 2024.",
        "liquidity_and_risk": "Liquidity improving.",
        "main_risks": "Overleveraged futures market.",
        "key_events_today": "FOMC minutes at 14:00 ET.",
        "scenarios": "Soft landing favored.",
        "actionable_insights": "Consider scaling into strength.",
        "probability_bullish_pct": 60,
        "probability_bearish_pct": 20,
        "probability_neutral_pct": 20,
    }
    payload.update(overrides)
    return payload


def _validation_error(payload: dict) -> ValidationError:
    try:
        AIAnalysisContent.model_validate(payload)
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError")


def test_recover_analysis_fields_replaces_only_the_invalid_string_field():
    payload = _valid_analysis_payload(main_risks=12345)

    recovered, failed = recover_analysis_fields(payload, _validation_error(payload))

    assert failed == ["main_risks"]
    assert recovered["main_risks"] == (
        "Not available this cycle -- the AI model returned an invalid value for this field."
    )
    assert recovered["what_changed"] == "BTC broke above 65k."
    AIAnalysisContent.model_validate(recovered)


def test_recover_analysis_fields_replaces_out_of_range_probability_with_zero():
    payload = _valid_analysis_payload(probability_bullish_pct=150)

    recovered, failed = recover_analysis_fields(payload, _validation_error(payload))

    assert failed == ["probability_bullish_pct"]
    assert recovered["probability_bullish_pct"] == 0
    AIAnalysisContent.model_validate(recovered)


def test_recover_analysis_fields_handles_multiple_failures_including_a_missing_key():
    payload = _valid_analysis_payload(main_risks=None, probability_bearish_pct=-5)
    del payload["scenarios"]

    recovered, failed = recover_analysis_fields(payload, _validation_error(payload))

    assert failed == ["main_risks", "probability_bearish_pct", "scenarios"]
    AIAnalysisContent.model_validate(recovered)


def test_format_data_quality_note_returns_none_without_recovered_fields():
    assert _format_data_quality_note(None) is None
    assert _format_data_quality_note([]) is None


def test_format_data_quality_note_names_the_recovered_fields():
    text = _format_data_quality_note(["main_risks", "scenarios"])

    assert "2 narrative field(s)" in text
    assert "main_risks, scenarios" in text


def test_build_institutional_report_includes_data_quality_note_when_fields_were_recovered():
    report = _report(
        institutional_summary={"scenarios": [], "analysis_recovered_fields": ["main_risks"]}
    )

    ir = build_institutional_report(report, sector_breadth=None)

    assert "main_risks" in ir["data_quality_note"]


def test_build_institutional_report_is_honest_when_no_fields_were_recovered():
    report = _report()

    ir = build_institutional_report(report, sector_breadth=None)

    assert ir["data_quality_note"] is None


# ---- Forecast Intelligence Upgrade: Regime-Aware Weighting -----------------


async def test_safe_reliability_uses_flat_method_without_a_live_regime():
    reliability_engine = AsyncMock()
    reliability_engine.evaluate_reliability.return_value = {"macro": 55.0}
    generator = _report_generator(reliability_engine)

    result = await generator._safe_reliability(None)

    assert result == {"macro": 55.0}
    reliability_engine.evaluate_reliability.assert_awaited_once()
    reliability_engine.evaluate_reliability_hierarchical.assert_not_called()


async def test_safe_reliability_uses_hierarchical_method_with_a_live_regime():
    reliability_engine = AsyncMock()
    reliability_engine.evaluate_reliability_hierarchical.return_value = {
        "macro": {"accuracy_pct": 62.0, "level": "regime", "effective_sample_size": 30},
        "crypto": {"accuracy_pct": None, "level": "insufficient_data", "effective_sample_size": 2},
    }
    generator = _report_generator(reliability_engine)

    result = await generator._safe_reliability("risk_off")

    assert result == {"macro": 62.0}
    reliability_engine.evaluate_reliability_hierarchical.assert_awaited_once_with(regime="risk_off")


async def test_safe_reliability_survives_reliability_engine_failure():
    reliability_engine = AsyncMock()
    reliability_engine.evaluate_reliability_hierarchical.side_effect = RuntimeError("db down")
    generator = _report_generator(reliability_engine)

    result = await generator._safe_reliability("bull")

    assert result is None


def test_report_generator_defaults_to_a_real_reliability_engine_when_none_is_injected():
    generator = ReportGenerator(
        session_factory=AsyncMock(),
        market_repository=AsyncMock(),
        news_repository=AsyncMock(),
        correlation_engine=AsyncMock(),
        regime_detector=AsyncMock(),
        signal_engine=AsyncMock(),
        agent_orchestrator=AsyncMock(),
    )

    assert isinstance(generator._reliability_engine, AgentReliabilityEngine)
