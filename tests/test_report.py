from app.database.models import (
    AssetClass,
    AssetPrice,
    MarketRegimeSnapshot,
    NewsCategory,
    NewsItem,
    NewsSentiment,
    SignalSnapshot,
)
from app.services.analysis.regime import MarketRegime
from app.services.analysis.report import build_user_prompt, derive_risk_level, strip_json_fence


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
