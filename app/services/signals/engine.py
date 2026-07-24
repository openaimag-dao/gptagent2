import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AssetPrice, NewsCategory, NewsItem, SignalSnapshot
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignalFactor:
    name: str
    points: int  # positive = bullish weight, negative = bearish weight


# The factor table from the spec: each condition, if it fires, contributes its
# signed point value. Positive points feed the bull score, negative points
# (in absolute value) feed the bear score.
FACTORS: tuple[SignalFactor, ...] = (
    SignalFactor("nasdaq_up", 2),
    SignalFactor("dxy_down", 3),
    SignalFactor("gold_up", -1),
    SignalFactor("etf_inflow", 5),
    SignalFactor("fed_dovish", 4),
    SignalFactor("vix_up", -3),
    SignalFactor("us10y_up", -2),
)


def _condition(
    name: str, by_symbol: dict[str, AssetPrice], etf_sentiment: float | None
) -> bool | None:
    """True/False if the factor's condition can be evaluated; None if the data is missing."""
    if name == "nasdaq_up":
        asset = by_symbol.get("NASDAQ")
        return None if asset is None or asset.change_pct_24h is None else asset.change_pct_24h > 0
    if name == "dxy_down":
        asset = by_symbol.get("DXY")
        return None if asset is None or asset.change_pct_24h is None else asset.change_pct_24h < 0
    if name == "gold_up":
        asset = by_symbol.get("GOLD")
        return None if asset is None or asset.change_pct_24h is None else asset.change_pct_24h > 0
    if name == "etf_inflow":
        # Proxy for actual ETF flow data (not collected): net sentiment of
        # recent ETF-category news. Positive net sentiment stands in for inflows.
        return None if etf_sentiment is None else etf_sentiment > 0
    if name == "fed_dovish":
        asset = by_symbol.get("FEDRATE")
        return None if asset is None or asset.change_24h is None else asset.change_24h < 0
    if name == "vix_up":
        asset = by_symbol.get("VIX")
        return None if asset is None or asset.change_pct_24h is None else asset.change_pct_24h > 0
    if name == "us10y_up":
        asset = by_symbol.get("US10Y")
        return None if asset is None or asset.change_24h is None else asset.change_24h > 0
    raise ValueError(f"Unknown signal factor: {name}")


def compute_signal(assets: list[AssetPrice], etf_sentiment: float | None) -> dict:
    """Pure bull/bear scoring function -- unit-testable without a database.

    Confidence % reflects how strongly the *available* signals agree in one
    net direction: abs(net_score) as a fraction of the total weight of every
    factor that could actually be evaluated this run.
    """
    by_symbol = {a.symbol: a for a in assets}

    bull_score = 0
    bear_score = 0
    available_weight = 0
    breakdown: dict[str, dict] = {}

    for factor in FACTORS:
        triggered = _condition(factor.name, by_symbol, etf_sentiment)
        breakdown[factor.name] = {"points": factor.points, "triggered": triggered}
        if triggered is None:
            continue
        available_weight += abs(factor.points)
        if triggered:
            if factor.points > 0:
                bull_score += factor.points
            else:
                bear_score += abs(factor.points)

    net_score = bull_score - bear_score
    confidence_pct = (
        min(round(100 * abs(net_score) / available_weight), 100) if available_weight else 0
    )

    return {
        "bull_score": bull_score,
        "bear_score": bear_score,
        "net_score": net_score,
        "confidence_pct": confidence_pct,
        "factors": breakdown,
    }


def _average_sentiment(items: list[NewsItem]) -> float | None:
    if not items:
        return None
    return sum(float(item.sentiment_score) for item in items) / len(items)


class SignalEngine:
    """Computes and persists the Bull/Bear signal score from the latest snapshot."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        market_repository: MarketRepository,
        news_repository: NewsRepository,
    ) -> None:
        self._session_factory = session_factory
        self._market_repository = market_repository
        self._news_repository = news_repository

    async def compute_and_store(self) -> SignalSnapshot:
        assets = await self._market_repository.get_latest()

        since = datetime.now(UTC) - timedelta(hours=24)
        recent_etf_news = await self._news_repository.get_recent(
            category=NewsCategory.ETF.value, limit=100, since=since
        )
        etf_sentiment = _average_sentiment(recent_etf_news)

        result = compute_signal(assets, etf_sentiment)

        snapshot = SignalSnapshot(
            bull_score=result["bull_score"],
            bear_score=result["bear_score"],
            net_score=result["net_score"],
            confidence_pct=result["confidence_pct"],
            factors=result["factors"],
        )
        async with self._session_factory() as session:
            session.add(snapshot)
            await session.commit()
            await session.refresh(snapshot)
        return snapshot

    async def get_latest(self) -> SignalSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(SignalSnapshot).order_by(SignalSnapshot.computed_at.desc()).limit(1)
            )
