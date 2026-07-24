import enum
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AssetPrice, MarketRegimeSnapshot
from app.services.market.repository import MarketRepository

logger = logging.getLogger(__name__)


class MarketRegime(str, enum.Enum):
    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    NEUTRAL = "neutral"
    LIQUIDITY_EXPANSION = "liquidity_expansion"
    LIQUIDITY_CONTRACTION = "liquidity_contraction"
    FLIGHT_TO_SAFETY = "flight_to_safety"


def _pct_change(by_symbol: dict[str, AssetPrice], symbol: str) -> float | None:
    asset = by_symbol.get(symbol)
    if asset is None or asset.change_pct_24h is None:
        return None
    return float(asset.change_pct_24h)


def _abs_change(by_symbol: dict[str, AssetPrice], symbol: str) -> float | None:
    asset = by_symbol.get(symbol)
    if asset is None or asset.change_24h is None:
        return None
    return float(asset.change_24h)


def detect_regime(assets: list[AssetPrice]) -> tuple[MarketRegime, dict[str, Any]]:
    """Deterministic, rule-based regime classification from the latest snapshot.

    Rules, in priority order:
    1. Flight to Safety -- equities and BTC both down, Gold up, yields down,
       VIX up: capital rotating out of risk assets into traditional havens.
    2. Liquidity Expansion / Contraction -- the Fed Funds Rate just moved.
       FEDFUNDS is a monthly series, so this only fires on the day a fresh
       observation lands (i.e. around an FOMC decision), and takes priority
       over the risk-on/off read because a rate move dominates positioning.
    3. Risk On / Risk Off -- equities, BTC, VIX and DXY all agree on direction.
    4. Neutral -- signals disagree, or there isn't enough data to decide.

    Returns the regime plus the raw inputs used, for auditability.
    """
    by_symbol = {a.symbol: a for a in assets}

    spx_chg = _pct_change(by_symbol, "SPX")
    btc_chg = _pct_change(by_symbol, "BTC")
    vix_chg = _pct_change(by_symbol, "VIX")
    dxy_chg = _pct_change(by_symbol, "DXY")
    gold_chg = _pct_change(by_symbol, "GOLD")
    us10y_chg = _abs_change(by_symbol, "US10Y")
    fedrate_chg = _abs_change(by_symbol, "FEDRATE")

    inputs: dict[str, Any] = {
        "spx_change_pct": spx_chg,
        "btc_change_pct": btc_chg,
        "vix_change_pct": vix_chg,
        "dxy_change_pct": dxy_chg,
        "gold_change_pct": gold_chg,
        "us10y_change": us10y_chg,
        "fedrate_change": fedrate_chg,
    }

    if (
        None not in (spx_chg, btc_chg, gold_chg, us10y_chg, vix_chg)
        and spx_chg < 0
        and btc_chg < 0
        and gold_chg > 0
        and us10y_chg < 0
        and vix_chg > 0
    ):
        return MarketRegime.FLIGHT_TO_SAFETY, inputs

    if fedrate_chg is not None and fedrate_chg < 0:
        return MarketRegime.LIQUIDITY_EXPANSION, inputs
    if fedrate_chg is not None and fedrate_chg > 0:
        return MarketRegime.LIQUIDITY_CONTRACTION, inputs

    if None not in (spx_chg, btc_chg, vix_chg, dxy_chg):
        if spx_chg > 0 and btc_chg > 0 and vix_chg < 0 and dxy_chg < 0:
            return MarketRegime.RISK_ON, inputs
        if spx_chg < 0 and btc_chg < 0 and vix_chg > 0 and dxy_chg > 0:
            return MarketRegime.RISK_OFF, inputs

    return MarketRegime.NEUTRAL, inputs


class RegimeDetector:
    """Detects and persists the current market regime from the latest snapshot."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        market_repository: MarketRepository,
    ) -> None:
        self._session_factory = session_factory
        self._market_repository = market_repository

    async def compute_and_store(self) -> MarketRegimeSnapshot:
        assets = await self._market_repository.get_latest()
        regime, inputs = detect_regime(assets)

        snapshot = MarketRegimeSnapshot(regime=regime, inputs=inputs)
        async with self._session_factory() as session:
            session.add(snapshot)
            await session.commit()
            await session.refresh(snapshot)
        return snapshot

    async def get_latest(self) -> MarketRegimeSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(MarketRegimeSnapshot).order_by(MarketRegimeSnapshot.computed_at.desc()).limit(1)
            )
