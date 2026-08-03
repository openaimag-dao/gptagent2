"""Formats SimilarMarketEngine's matches into plain text for the report LLM
prompt -- real dates, real outcomes, real events, nothing invented.

v12.0 P2: this module used to own its own independent RSI/volatility
distance search (`KnowledgeEngine.find_analogs`) that duplicated exactly
what SimilarMarketEngine already computed, producing two different
similarity answers to the same question. That search now lives in one
place only (`SimilarMarketEngine.find_similar_periods`, opt-in
`include_nearby_events=True`); this module keeps only the
report-formatting helper that was its unique remaining value.
"""

_GROUNDING_HORIZON = "7d"


def build_grounding_text(symbol: str, matches: list[dict]) -> str:
    if not matches:
        return f"- No sufficiently similar historical episode found for {symbol}."

    lines = [f"- {symbol} conditions today most resemble:"]
    for match in matches:
        date_str = match["date"].date().isoformat()
        forward = match["forward_returns_pct"].get(_GROUNDING_HORIZON)
        forward_str = f"{forward:+.2f}%" if forward is not None else "n/a"
        line = f"  - {date_str} (RSI {match['rsi']:.1f}): next-period return was {forward_str}"
        nearby = match.get("nearby_events") or []
        if nearby:
            titles = ", ".join(e["title"] for e in nearby)
            line += f" -- nearby event(s): {titles}"
        lines.append(line)
    return "\n".join(lines)
