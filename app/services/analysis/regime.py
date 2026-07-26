import enum
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AssetPrice, FeatureSnapshot, MarketRegimeSnapshot, WhaleSnapshot
from app.services.market.repository import MarketRepository

logger = logging.getLogger(__name__)

_CAPITULATION_BTC_DROP_PCT = -8.0
_CAPITULATION_VIX_SPIKE_PCT = 15.0
_BULL_BEAR_MOMENTUM_PCT = 10.0
_SIDEWAYS_MAX_MOVE_PCT = 0.3


class MarketRegime(str, enum.Enum):
    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    NEUTRAL = "neutral"
    LIQUIDITY_EXPANSION = "liquidity_expansion"
    LIQUIDITY_CONTRACTION = "liquidity_contraction"
    FLIGHT_TO_SAFETY = "flight_to_safety"
    BULL = "bull"
    BEAR = "bear"
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    CAPITULATION = "capitulation"
    RECOVERY = "recovery"
    SIDEWAYS = "sideways"


_RECOVERY_PRIOR_REGIMES = frozenset({MarketRegime.BEAR, MarketRegime.CAPITULATION})


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


def detect_regime(
    assets: list[AssetPrice],
    whale_classification: str | None = None,
    momentum_30d: dict[str, float] | None = None,
    previous_regime: MarketRegime | None = None,
) -> tuple[MarketRegime, dict[str, Any]]:
    """Deterministic, rule-based regime classification from the latest snapshot.

    Rules, in priority order:
    1. Flight to Safety -- equities and BTC both down, Gold up, yields down,
       VIX up: capital rotating out of risk assets into traditional havens.
    2. Capitulation -- an extreme, panic-scale single-day drop (BTC down
       >8%, VIX up >15%): a sharper, more acute read than plain Risk Off.
    3. Liquidity Expansion / Contraction -- the Fed Funds Rate just moved.
       FEDFUNDS is a monthly series, so this only fires on the day a fresh
       observation lands (i.e. around an FOMC decision), and takes priority
       over the risk-on/off read because a rate move dominates positioning.
    4. Bull / Bear -- needs `momentum_30d` (from the Feature Engine, e.g.
       FeatureSnapshot.features["momentum_30d_pct"]): BTC and SPX both up
       or both down >10% over 30 days. A sustained-trend read, distinct
       from a single day's Risk On/Off.
    5. Accumulation / Distribution -- needs `whale_classification` (from
       WhaleIntelligenceEngine: "long_heavy"/"short_heavy"/"balanced",
       itself derived from CoinGlass/Coinalyze funding rate + long/short
       ratio). This is a derivatives-positioning proxy, NOT literal
       on-chain wallet accumulation/distribution -- there's no free source
       for that (see app/services/whales/engine.py's own docstring for the
       same caveat). Fires when price is roughly flat but positioning is
       lopsided: long-heavy + flat/down price suggests leveraged buyers
       building into weakness ("accumulation"); short-heavy + flat/up
       price suggests leveraged sellers building into strength
       ("distribution").
    6. Risk On / Risk Off -- equities, BTC, VIX and DXY all agree on direction.
    7. Recovery -- needs `previous_regime`: BTC/SPX both positive today,
       immediately following a Bear or Capitulation read.
    8. Sideways -- every available signal is essentially flat (<0.3% move).
    9. Neutral -- signals disagree, or there isn't enough data to decide.

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
        "whale_classification": whale_classification,
        "momentum_30d": momentum_30d,
        "previous_regime": previous_regime.value if previous_regime else None,
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

    if (
        btc_chg is not None
        and vix_chg is not None
        and btc_chg <= _CAPITULATION_BTC_DROP_PCT
        and vix_chg >= _CAPITULATION_VIX_SPIKE_PCT
    ):
        return MarketRegime.CAPITULATION, inputs

    if fedrate_chg is not None and fedrate_chg < 0:
        return MarketRegime.LIQUIDITY_EXPANSION, inputs
    if fedrate_chg is not None and fedrate_chg > 0:
        return MarketRegime.LIQUIDITY_CONTRACTION, inputs

    if momentum_30d:
        btc_mom = momentum_30d.get("BTC")
        spx_mom = momentum_30d.get("SPX")
        if btc_mom is not None and spx_mom is not None:
            if btc_mom >= _BULL_BEAR_MOMENTUM_PCT and spx_mom >= _BULL_BEAR_MOMENTUM_PCT:
                return MarketRegime.BULL, inputs
            if btc_mom <= -_BULL_BEAR_MOMENTUM_PCT and spx_mom <= -_BULL_BEAR_MOMENTUM_PCT:
                return MarketRegime.BEAR, inputs

    if whale_classification is not None and btc_chg is not None:
        if whale_classification == "long_heavy" and btc_chg <= 2.0:
            return MarketRegime.ACCUMULATION, inputs
        if whale_classification == "short_heavy" and btc_chg >= -2.0:
            return MarketRegime.DISTRIBUTION, inputs

    if None not in (spx_chg, btc_chg, vix_chg, dxy_chg):
        if spx_chg > 0 and btc_chg > 0 and vix_chg < 0 and dxy_chg < 0:
            if previous_regime in _RECOVERY_PRIOR_REGIMES:
                return MarketRegime.RECOVERY, inputs
            return MarketRegime.RISK_ON, inputs
        if spx_chg < 0 and btc_chg < 0 and vix_chg > 0 and dxy_chg > 0:
            return MarketRegime.RISK_OFF, inputs

    if (
        None not in (spx_chg, btc_chg)
        and abs(spx_chg) < _SIDEWAYS_MAX_MOVE_PCT
        and abs(btc_chg) < _SIDEWAYS_MAX_MOVE_PCT
    ):
        return MarketRegime.SIDEWAYS, inputs

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

    async def _latest_whale_classification(self) -> str | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(WhaleSnapshot)
                .where(WhaleSnapshot.symbol == "BTC", WhaleSnapshot.available)
                .order_by(WhaleSnapshot.computed_at.desc())
                .limit(1)
            )
        return row.classification if row is not None else None

    async def _latest_momentum_30d(self) -> dict[str, float]:
        momentum: dict[str, float] = {}
        async with self._session_factory() as session:
            for symbol in ("BTC", "SPX"):
                row = await session.scalar(
                    select(FeatureSnapshot)
                    .where(FeatureSnapshot.symbol == symbol)
                    .order_by(FeatureSnapshot.computed_at.desc())
                    .limit(1)
                )
                value = row.features.get("momentum_30d_pct") if row is not None else None
                if value is not None:
                    momentum[symbol] = value
        return momentum

    async def compute_and_store(self) -> MarketRegimeSnapshot:
        assets = await self._market_repository.get_latest()
        previous = await self.get_latest()
        whale_classification = await self._latest_whale_classification()
        momentum_30d = await self._latest_momentum_30d()

        regime, inputs = detect_regime(
            assets,
            whale_classification=whale_classification,
            momentum_30d=momentum_30d,
            previous_regime=MarketRegime(previous.regime.value) if previous else None,
        )

        snapshot = MarketRegimeSnapshot(regime=regime, inputs=inputs)
        async with self._session_factory() as session:
            session.add(snapshot)
            await session.commit()
            await session.refresh(snapshot)
        return snapshot

    async def get_latest(self) -> MarketRegimeSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(MarketRegimeSnapshot)
                .order_by(MarketRegimeSnapshot.computed_at.desc())
                .limit(1)
            )
