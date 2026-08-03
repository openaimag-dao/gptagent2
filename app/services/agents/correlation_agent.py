"""Correlation Agent -- CorrelationEngine (app/services/analysis/
correlation.py) computes real rolling Pearson correlations for a fixed set
of pairs, but only ever as an unsigned strength between two assets moving
together or apart -- there is no existing derivation anywhere in this
project that turns "BTC and DXY are -0.6 correlated" into a directional
call for BTC itself (that would require a second, independent read on
which way the correlated asset is trending, which this engine does not
have). Rather than inventing that composition under time pressure, this
agent honestly reports no direction -- matching OnchainAgent's honesty
pattern -- while still surfacing the real correlation data it has.
"""

from app.services.agents.base import AgentOutput
from app.services.analysis.correlation import CorrelationEngine

PROXY_SYMBOL = "BTC"


class CorrelationAgent:
    def __init__(self, correlation_engine: CorrelationEngine) -> None:
        self._correlation_engine = correlation_engine

    async def summarize(self) -> AgentOutput:
        correlations = await self._correlation_engine.get_latest()
        relevant = [c for c in correlations if PROXY_SYMBOL in (c.symbol_a, c.symbol_b)]

        if not relevant:
            lines = ["*CORRELATION SUMMARY*", "", "No correlations computed yet."]
            return AgentOutput(
                agent="correlation", summary="\n".join(lines), data={"available": False}
            )

        lines = ["*CORRELATION SUMMARY*", ""]
        lines.extend(
            f"{c.symbol_a}/{c.symbol_b} ({c.window_days}d): {float(c.correlation):.2f}"
            for c in relevant
        )
        lines.append("")
        lines.append(
            "No directional call: correlation strength alone does not indicate which way "
            f"{PROXY_SYMBOL} itself is trending."
        )

        return AgentOutput(
            agent="correlation",
            summary="\n".join(lines),
            data={
                "available": True,
                "pairs": [
                    {
                        "symbol_a": c.symbol_a,
                        "symbol_b": c.symbol_b,
                        "window_days": c.window_days,
                        "correlation": float(c.correlation),
                    }
                    for c in relevant
                ],
            },
        )
