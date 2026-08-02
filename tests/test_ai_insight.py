from app.services.common.ai_insight import build_ai_insight, format_ai_insight_lines


def test_build_ai_insight_defaults_unpopulated_fields_to_none_or_empty():
    insight = build_ai_insight(current_status="Bull regime")

    assert insight["current_status"] == "Bull regime"
    assert insight["ai_conclusion"] is None
    assert insight["supporting_evidence"] == []
    assert insight["confidence"] is None


def test_build_ai_insight_never_fabricates_missing_fields():
    insight = build_ai_insight()

    assert all(
        insight[key] is None
        for key in (
            "current_status",
            "ai_conclusion",
            "why",
            "committee_opinion",
            "consensus",
            "historical_similarity",
            "main_opportunity",
            "main_risk",
            "expected_scenario",
            "what_to_watch_next",
            "confidence",
        )
    )
    assert insight["supporting_evidence"] == []


def test_format_ai_insight_lines_only_renders_populated_fields():
    insight = build_ai_insight(current_status="Bull regime -- health 80/100.")

    lines = format_ai_insight_lines(insight)

    assert lines == ["Current Status: Bull regime -- health 80/100."]


def test_format_ai_insight_lines_renders_in_spec_order():
    insight = build_ai_insight(
        current_status="status",
        ai_conclusion="conclusion",
        why="why",
        supporting_evidence=["agent1: evidence1"],
        committee_opinion="BUY (70%)",
        consensus="bullish 60%",
        historical_similarity="Similar to 2024 rally",
        main_opportunity="upside breakout",
        main_risk="macro shock",
        expected_scenario="continuation",
        what_to_watch_next="CPI print",
        confidence=82.0,
    )

    lines = format_ai_insight_lines(insight)

    assert lines == [
        "Current Status: status",
        "AI Conclusion: conclusion",
        "Why: why",
        "Committee Opinion: BUY (70%)",
        "Consensus: bullish 60%",
        "Historical Similarity: Similar to 2024 rally",
        "Main Opportunity: upside breakout",
        "Main Risk: macro shock",
        "Expected Scenario: continuation",
        "What To Watch Next: CPI print",
        "Supporting Evidence:",
        "- agent1: evidence1",
        "Confidence: 82.0%",
    ]


def test_format_ai_insight_lines_empty_dict_yields_no_lines():
    assert format_ai_insight_lines(build_ai_insight()) == []
