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
    build_institutional_report,
    build_user_prompt,
    derive_risk_level,
    strip_json_fence,
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

    assert "Risk On regime" in ir["executive_summary"]
    assert "BTC broke above 65k." in ir["executive_summary"]
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


def test_build_institutional_report_is_honest_when_scenarios_and_breadth_are_missing():
    report = _report(institutional_summary={})

    ir = build_institutional_report(report, sector_breadth=None)

    assert ir["biggest_opportunity"] == "No bullish scenario currently dominant."
    assert ir["biggest_risk"] == "No bearish scenario currently dominant."
    assert "unavailable" in ir["sector_rotation"]
