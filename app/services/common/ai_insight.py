"""v10.0 "Unified Intelligence Experience" -- a reusable AI Insight shape
every major page can compose into, from data it already has. This module
adds no new computation of its own: `build_ai_insight()` just names and
orders the fields the mission's spec asks every page to answer (current
status, AI conclusion, why, evidence, committee opinion, consensus,
historical similarity, main opportunity, main risk, expected scenario,
what to watch next, confidence), and `format_ai_insight_lines()` renders
whichever of those fields a caller actually populated as a standard,
consistently-worded Telegram block -- so different screens stop inventing
their own label for the same concept (e.g. "Biggest Risk" vs "Highest
Risk" vs "Main Threat" all becoming "Main Risk").

A field a caller doesn't pass is simply absent from both the dict and the
rendered lines -- never a fabricated "n/a" filler.
"""


def build_ai_insight(
    *,
    current_status: str | None = None,
    ai_conclusion: str | None = None,
    why: str | None = None,
    supporting_evidence: list[str] | None = None,
    committee_opinion: str | None = None,
    consensus: str | None = None,
    historical_similarity: str | None = None,
    main_opportunity: str | None = None,
    main_risk: str | None = None,
    expected_scenario: str | None = None,
    what_to_watch_next: str | None = None,
    confidence: float | None = None,
) -> dict:
    return {
        "current_status": current_status,
        "ai_conclusion": ai_conclusion,
        "why": why,
        "supporting_evidence": supporting_evidence or [],
        "committee_opinion": committee_opinion,
        "consensus": consensus,
        "historical_similarity": historical_similarity,
        "main_opportunity": main_opportunity,
        "main_risk": main_risk,
        "expected_scenario": expected_scenario,
        "what_to_watch_next": what_to_watch_next,
        "confidence": confidence,
    }


# Standard label per field -- the single source of truth for wording other
# formatters should converge on (see v10.0's "Consistent Terminology" pass).
_FIELD_LABELS: tuple[tuple[str, str], ...] = (
    ("current_status", "Current Status"),
    ("ai_conclusion", "AI Conclusion"),
    ("why", "Why"),
    ("committee_opinion", "Committee Opinion"),
    ("consensus", "Consensus"),
    ("historical_similarity", "Historical Similarity"),
    ("main_opportunity", "Main Opportunity"),
    ("main_risk", "Main Risk"),
    ("expected_scenario", "Expected Scenario"),
    ("what_to_watch_next", "What To Watch Next"),
)


def format_ai_insight_lines(insight: dict) -> list[str]:
    """Renders whichever fields of an build_ai_insight() dict are populated
    as `Label: value` lines, plus a bulleted Supporting Evidence block and a
    trailing Confidence line -- in the mission's specified order. Callers
    embed this list into their own format_*() output rather than
    duplicating the label wording themselves."""
    lines: list[str] = []
    for key, label in _FIELD_LABELS:
        value = insight.get(key)
        if value:
            lines.append(f"{label}: {value}")
    evidence = insight.get("supporting_evidence")
    if evidence:
        lines.append("Supporting Evidence:")
        lines.extend(f"- {item}" for item in evidence)
    confidence = insight.get("confidence")
    if confidence is not None:
        lines.append(f"Confidence: {confidence}%")
    return lines
