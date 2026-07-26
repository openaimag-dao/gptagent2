"""Global Market Score -- a deterministic composite of every existing engine's
output. No new data: pure aggregation of regime inputs, the signal engine's
factor breakdown, and live asset changes, so every sub-score can be traced
back to a real, already-computed number."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AssetPrice, GlobalMarketScore
from app.services.analysis.regime import MarketRegime, RegimeDetector
from app.services.common.scoring import center_scaled, clamp
from app.services.market.repository import MarketRepository
from app.services.signals.engine import SignalEngine

logger = logging.getLogger(__name__)

_CRYPTO_SYMBOLS = ("BTC", "ETH", "SOL")
_STOCK_SYMBOLS = ("NASDAQ", "SPX", "DJI", "RUT")

_REGIME_RISK_SPLIT: dict[MarketRegime, tuple[int, int]] = {
    MarketRegime.RISK_ON: (85, 15),
    MarketRegime.RISK_OFF: (15, 85),
    MarketRegime.NEUTRAL: (50, 50),
    MarketRegime.LIQUIDITY_EXPANSION: (70, 30),
    MarketRegime.LIQUIDITY_CONTRACTION: (30, 70),
    MarketRegime.FLIGHT_TO_SAFETY: (10, 90),
}


def _average_change(assets: list[AssetPrice], symbols: tuple[str, ...]) -> float | None:
    by_symbol = {a.symbol: a for a in assets}
    changes = [
        float(by_symbol[s].change_pct_24h)
        for s in symbols
        if s in by_symbol and by_symbol[s].change_pct_24h is not None
    ]
    return sum(changes) / len(changes) if changes else None


def compute_global_score(
    regime: MarketRegime,
    regime_inputs: dict[str, Any],
    signal_factors: dict[str, dict],
    assets: list[AssetPrice],
) -> dict:
    """Pure aggregation -- every sub-score is traceable to an already-computed
    input, nothing is invented. Returns a dict matching GlobalMarketScore's
    persisted columns."""
    risk_on, risk_off = _REGIME_RISK_SPLIT[regime]

    fedrate_change = regime_inputs.get("fedrate_change")
    liquidity_score = center_scaled(
        -fedrate_change if fedrate_change is not None else None, scale=40.0
    )

    vix_change = regime_inputs.get("vix_change_pct")
    fear_score = center_scaled(vix_change, scale=4.0)
    greed_score = clamp(100 - fear_score)

    dxy_change = regime_inputs.get("dxy_change_pct")
    us10y_change = regime_inputs.get("us10y_change")
    macro_pressure_terms = [t for t in (dxy_change, us10y_change) if t is not None]
    macro_pressure_score = (
        center_scaled(sum(macro_pressure_terms), scale=10.0) if macro_pressure_terms else 50.0
    )

    etf_factor = signal_factors.get("etf_inflow", {})
    etf_triggered = etf_factor.get("triggered")
    institutional_activity_score = (
        75.0 if etf_triggered is True else 25.0 if etf_triggered is False else 50.0
    )

    crypto_strength_score = center_scaled(_average_change(assets, _CRYPTO_SYMBOLS), scale=5.0)
    stock_strength_score = center_scaled(_average_change(assets, _STOCK_SYMBOLS), scale=8.0)

    global_score = clamp(
        0.20 * risk_on
        + 0.15 * liquidity_score
        + 0.15 * greed_score
        + 0.15 * (100 - macro_pressure_score)
        + 0.10 * institutional_activity_score
        + 0.125 * crypto_strength_score
        + 0.125 * stock_strength_score
    )

    return {
        "risk_on_score": round(risk_on),
        "risk_off_score": round(risk_off),
        "liquidity_score": round(liquidity_score),
        "fear_score": round(fear_score),
        "greed_score": round(greed_score),
        "macro_pressure_score": round(macro_pressure_score),
        "institutional_activity_score": round(institutional_activity_score),
        "crypto_strength_score": round(crypto_strength_score),
        "stock_strength_score": round(stock_strength_score),
        "global_score": round(global_score),
    }


class GlobalScoreEngine:
    """Computes and persists the Global Market Score from the latest snapshot."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        market_repository: MarketRepository,
        regime_detector: RegimeDetector,
        signal_engine: SignalEngine,
    ) -> None:
        self._session_factory = session_factory
        self._market_repository = market_repository
        self._regime_detector = regime_detector
        self._signal_engine = signal_engine

    async def compute_and_store(self) -> GlobalMarketScore | None:
        assets = await self._market_repository.get_latest()
        regime_snapshot = await self._regime_detector.get_latest()
        signal_snapshot = await self._signal_engine.get_latest()
        if regime_snapshot is None or signal_snapshot is None:
            return None

        scores = compute_global_score(
            MarketRegime(regime_snapshot.regime),
            regime_snapshot.inputs,
            signal_snapshot.factors,
            assets,
        )

        row = GlobalMarketScore(**scores, inputs=regime_snapshot.inputs)
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def get_latest(self) -> GlobalMarketScore | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(GlobalMarketScore).order_by(GlobalMarketScore.computed_at.desc()).limit(1)
            )
