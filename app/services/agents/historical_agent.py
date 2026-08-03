"""Historical Agent -- votes off SimilarMarketEngine's own real historical
analog matches (the same RSI/volatility-distance search Explainability's
"Historical Patterns" row and the Replay/Terminal pages already use): the
7-day forward return real similar-history episodes actually realized,
averaged, sign-thresholded the same way ExplainabilityEngine's own
`_historical_signal_and_explanation` already does. Confidence is the
average real similarity score across those matches -- how closely history
actually resembles today -- not a fabricated number.
"""

from app.services.agents.base import AgentOutput
from app.services.history.registry import find_symbol_config
from app.services.history.schemas import Timeframe
from app.services.similar_market.engine import SimilarMarketEngine

PROXY_SYMBOL = "BTC"
_MATCH_COUNT = 10
_NEUTRAL_BAND_PCT = 0.5


def _historical_direction(matches: list[dict]) -> tuple[str | None, float | None]:
    """Pure function: real 7-day forward returns from similar historical
    episodes -> (direction, confidence). None when no matches have a real
    7-day forward return yet (never a guessed vote)."""
    returns = [
        m["forward_returns_pct"].get("7d")
        for m in matches
        if m.get("forward_returns_pct", {}).get("7d") is not None
    ]
    if not returns:
        return None, None
    avg_return = sum(returns) / len(returns)
    if avg_return > _NEUTRAL_BAND_PCT:
        direction = "bullish"
    elif avg_return < -_NEUTRAL_BAND_PCT:
        direction = "bearish"
    else:
        direction = "neutral"

    similarities = [m["similarity"] for m in matches if m.get("similarity") is not None]
    confidence = round(sum(similarities) / len(similarities), 1) if similarities else None
    return direction, confidence


class HistoricalAgent:
    def __init__(self, similar_market_engine: SimilarMarketEngine) -> None:
        self._similar_market_engine = similar_market_engine

    async def summarize(self) -> AgentOutput:
        config = find_symbol_config(PROXY_SYMBOL)
        matches = (
            await self._similar_market_engine.find_similar_periods(
                config.symbol, config.model, Timeframe.DAILY, k=_MATCH_COUNT
            )
            if config is not None
            else []
        )

        if not matches:
            lines = ["*HISTORICAL SUMMARY*", "", "No similar historical periods found yet."]
            return AgentOutput(
                agent="historical", summary="\n".join(lines), data={"available": False}
            )

        direction, confidence = _historical_direction(matches)

        lines = ["*HISTORICAL SUMMARY*", ""]
        lines.extend(
            f"{m['date'].date()} (similarity {m['similarity']}%): "
            f"7d forward {m['forward_returns_pct'].get('7d')}%"
            for m in matches[:5]
        )

        return AgentOutput(
            agent="historical",
            summary="\n".join(lines),
            data={
                "available": True,
                "match_count": len(matches),
                "avg_similarity": confidence,
            },
            direction=direction,
            confidence=confidence,
        )
