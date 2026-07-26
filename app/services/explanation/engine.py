"""Explanation Engine -- assembles an "evidence pack" for the current
signal read: triggered indicators, macro drivers, historical examples,
supporting news, risk factors and an alternative view. Every field is
pulled from data another engine already computed and persisted; this
engine does no independent analysis of its own, only assembly.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import NewsSentiment, SimilarMarketMatch
from app.services.analysis.regime import RegimeDetector
from app.services.global_score.engine import GlobalScoreEngine
from app.services.news.repository import NewsRepository
from app.services.scenarios.engine import ScenarioEngine
from app.services.signals.engine import SignalEngine

_HISTORICAL_EXAMPLES_LIMIT = 3
_SUPPORTING_NEWS_LIMIT = 5


class ExplanationEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        signal_engine: SignalEngine,
        regime_detector: RegimeDetector,
        news_repository: NewsRepository,
        global_score_engine: GlobalScoreEngine,
        scenario_engine: ScenarioEngine,
    ) -> None:
        self._session_factory = session_factory
        self._signal_engine = signal_engine
        self._regime_detector = regime_detector
        self._news_repository = news_repository
        self._global_score_engine = global_score_engine
        self._scenario_engine = scenario_engine

    async def _recent_similar_matches(self, symbol: str) -> list[SimilarMarketMatch]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(SimilarMarketMatch)
                .where(SimilarMarketMatch.symbol == symbol.upper())
                .order_by(SimilarMarketMatch.computed_at.desc())
                .limit(_HISTORICAL_EXAMPLES_LIMIT)
            )
            return list(result)

    async def build(self, symbol: str = "BTC") -> dict:
        signal_snapshot = await self._signal_engine.get_latest()
        regime_snapshot = await self._regime_detector.get_latest()
        global_score = await self._global_score_engine.get_latest()
        scenario_snapshot = await self._scenario_engine.get_latest()
        matches = await self._recent_similar_matches(symbol)

        if signal_snapshot is not None and signal_snapshot.net_score > 0:
            wanted_sentiment = NewsSentiment.BULLISH
        elif signal_snapshot is not None and signal_snapshot.net_score < 0:
            wanted_sentiment = NewsSentiment.BEARISH
        else:
            wanted_sentiment = None

        news_items = await self._news_repository.get_recent(limit=20)
        supporting_news = [
            {"title": item.title, "sentiment": item.sentiment.value, "url": item.url}
            for item in news_items
            if wanted_sentiment is None or item.sentiment == wanted_sentiment
        ][:_SUPPORTING_NEWS_LIMIT]

        indicators = (
            [
                {"name": name, **data}
                for name, data in signal_snapshot.factors.items()
                if data.get("triggered") is True
            ]
            if signal_snapshot is not None
            else []
        )

        macro_drivers = regime_snapshot.inputs if regime_snapshot is not None else {}

        historical_examples = [
            {
                "match_timestamp": m.match_timestamp.isoformat(),
                "similarity_score": float(m.similarity_score),
                "regime": m.market_regime,
                "forward_return_7d_pct": (
                    float(m.forward_return_7d_pct) if m.forward_return_7d_pct is not None else None
                ),
            }
            for m in matches
        ]

        risk_factors = (
            {
                "fear_score": global_score.fear_score,
                "macro_pressure_score": global_score.macro_pressure_score,
                "risk_off_score": global_score.risk_off_score,
            }
            if global_score is not None
            else None
        )

        alternative_view = None
        if scenario_snapshot is not None and scenario_snapshot.scenarios:
            ranked = sorted(
                scenario_snapshot.scenarios, key=lambda s: s["probability_pct"], reverse=True
            )
            if len(ranked) > 1:
                alternative_view = ranked[1]

        return {
            "symbol": symbol.upper(),
            "indicators": indicators,
            "macro_drivers": macro_drivers,
            "historical_examples": historical_examples,
            "supporting_news": supporting_news,
            "risk_factors": risk_factors,
            "alternative_view": alternative_view,
        }
