"""On-chain Agent -- OnChainIntelligenceEngine is a documented no-data-source
scaffold (see app/services/onchain/engine.py): every metric is always
unavailable today. This agent honestly reports no direction rather than
fabricating a signal from nothing -- it activates on its own, with no code
change here, the day a real on-chain provider (Glassnode/Helius) is wired
in and `available` starts coming back True.
"""

from app.services.agents.base import AgentOutput
from app.services.onchain.engine import OnChainIntelligenceEngine

PROXY_SYMBOL = "BTC"


class OnchainAgent:
    def __init__(self, onchain_engine: OnChainIntelligenceEngine) -> None:
        self._onchain_engine = onchain_engine

    async def summarize(self) -> AgentOutput:
        snapshot = await self._onchain_engine.get_snapshot(PROXY_SYMBOL)

        lines = ["*ON-CHAIN SUMMARY*", "", snapshot.get("reason", "Unavailable.")]

        return AgentOutput(
            agent="onchain",
            summary="\n".join(lines),
            data={"available": snapshot.get("available", False), "reason": snapshot.get("reason")},
        )
