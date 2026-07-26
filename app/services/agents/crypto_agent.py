"""Crypto Agent -- BTC/ETH/SOL/TOTAL/BTC.D, whale intelligence and ETF flow
proxy. Reuses WhaleIntelligenceEngine and ETFIntelligenceEngine as-is
(including their honest "unavailable" responses) rather than
reimplementing on-chain analysis."""

from app.services.agents.base import AgentOutput
from app.services.common.formatting import asset_change_dict, format_asset_lines
from app.services.etf.engine import ETFIntelligenceEngine
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository
from app.services.whales.engine import WhaleIntelligenceEngine

CRYPTO_SYMBOLS: tuple[str, ...] = ("BTC", "ETH", "SOL", "TOTAL", "BTC.D")


class CryptoAgent:
    def __init__(
        self,
        market_repository: MarketRepository,
        global_score_engine: GlobalScoreEngine,
        whale_engine: WhaleIntelligenceEngine,
        etf_engine: ETFIntelligenceEngine,
    ) -> None:
        self._market_repository = market_repository
        self._global_score_engine = global_score_engine
        self._whale_engine = whale_engine
        self._etf_engine = etf_engine

    async def summarize(self) -> AgentOutput:
        assets = await self._market_repository.get_latest()
        global_score = await self._global_score_engine.get_latest()
        whale_snapshot = await self._whale_engine.get_snapshot("BTC")
        etf_proxy = await self._etf_engine.get_flow_proxy()

        lines = ["*CRYPTO SUMMARY*", ""]
        lines.extend(format_asset_lines(assets, CRYPTO_SYMBOLS))
        lines.append("")
        if global_score is not None:
            lines.append(f"Crypto strength: {global_score.crypto_strength_score}/100")

        if whale_snapshot.get("available"):
            institutional_behavior = f"Whale classification: {whale_snapshot.get('classification')}"
        else:
            institutional_behavior = f"Whale data: {whale_snapshot.get('reason')}"
        lines.append(institutional_behavior)

        if etf_proxy.get("available"):
            market_structure = f"ETF sentiment proxy: {etf_proxy.get('classification')}"
        else:
            market_structure = f"ETF proxy: {etf_proxy.get('reason', 'no data')}"
        lines.append(market_structure)

        return AgentOutput(
            agent="crypto",
            summary="\n".join(lines),
            data={
                "assets": asset_change_dict(assets, CRYPTO_SYMBOLS),
                "institutional_behavior": institutional_behavior,
                "market_structure": market_structure,
                "whale_snapshot": whale_snapshot,
                "etf_flow_proxy": etf_proxy,
            },
        )
