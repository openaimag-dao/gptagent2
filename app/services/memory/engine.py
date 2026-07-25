"""Market Memory Engine -- a unified, read-only view across every table this
project already persists (predictions, signals, regime, correlations,
patterns, similarity matches, knowledge rules, whale/ETF snapshots,
sentiment, macro events, news). Nothing new is computed or stored here;
this only queries and normalizes what every other engine already writes,
so "never lose history" holds without a second copy of the data.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import (
    AlertLog,
    Correlation,
    EtfFlowSnapshot,
    GlobalMarketScore,
    HistoricalEvent,
    KnowledgeRule,
    MarketRegimeSnapshot,
    NewsItem,
    PatternSignal,
    ProbabilitySnapshot,
    SentimentSnapshot,
    SignalSnapshot,
    SimilarMarketMatch,
    WhaleSnapshot,
)


@dataclass(frozen=True)
class _CategorySpec:
    model: type
    timestamp_column: str
    serialize: Callable[[object], dict]


def _predictions_summary(row: ProbabilitySnapshot) -> dict:
    return {
        "symbol": row.symbol,
        "timeframe": row.timeframe.value,
        "prob_up_pct": row.prob_up_pct,
        "prob_down_pct": row.prob_down_pct,
        "prob_flat_pct": row.prob_flat_pct,
    }


def _signals_summary(row: SignalSnapshot) -> dict:
    return {
        "bull_score": row.bull_score,
        "bear_score": row.bear_score,
        "net_score": row.net_score,
        "confidence_pct": row.confidence_pct,
    }


def _regime_summary(row: MarketRegimeSnapshot) -> dict:
    return {"regime": row.regime.value}


def _correlations_summary(row: Correlation) -> dict:
    return {
        "pair": f"{row.symbol_a}/{row.symbol_b}",
        "window_days": row.window_days,
        "correlation": float(row.correlation),
    }


def _patterns_summary(row: PatternSignal) -> dict:
    return {"symbol": row.symbol, "pattern": row.pattern_name, "direction": row.direction.value}


def _similarity_summary(row: SimilarMarketMatch) -> dict:
    return {
        "symbol": row.symbol,
        "match_timestamp": row.match_timestamp.isoformat(),
        "similarity_score": float(row.similarity_score),
    }


def _knowledge_rules_summary(row: KnowledgeRule) -> dict:
    return {
        "title": row.title,
        "category": row.category.value,
        "win_rate_pct": float(row.win_rate_pct) if row.win_rate_pct is not None else None,
    }


def _whale_summary(row: WhaleSnapshot) -> dict:
    return {"symbol": row.symbol, "available": row.available, "classification": row.classification}


def _etf_summary(row: EtfFlowSnapshot) -> dict:
    return {"available": row.available, "classification": row.classification}


def _sentiment_summary(row: SentimentSnapshot) -> dict:
    return {
        "fear_greed_value": row.fear_greed_value,
        "global_sentiment_score": row.global_sentiment_score,
    }


def _global_score_summary(row: GlobalMarketScore) -> dict:
    return {"global_score": row.global_score}


def _news_summary(row: NewsItem) -> dict:
    return {"title": row.title, "category": row.category.value, "sentiment": row.sentiment.value}


def _macro_events_summary(row: HistoricalEvent) -> dict:
    return {"title": row.title, "category": row.category.value}


def _alerts_summary(row: AlertLog) -> dict:
    return {
        "alert_type": row.alert_type,
        "message": row.message,
        "conviction_tier": row.conviction_tier,
        "broadcast": row.broadcast,
    }


_CATEGORIES: dict[str, _CategorySpec] = {
    "predictions": _CategorySpec(ProbabilitySnapshot, "computed_at", _predictions_summary),
    "signals": _CategorySpec(SignalSnapshot, "computed_at", _signals_summary),
    "regime": _CategorySpec(MarketRegimeSnapshot, "computed_at", _regime_summary),
    "correlations": _CategorySpec(Correlation, "calculated_at", _correlations_summary),
    "patterns": _CategorySpec(PatternSignal, "timestamp", _patterns_summary),
    "similarity": _CategorySpec(SimilarMarketMatch, "computed_at", _similarity_summary),
    "knowledge_rules": _CategorySpec(KnowledgeRule, "created_at", _knowledge_rules_summary),
    "whale": _CategorySpec(WhaleSnapshot, "computed_at", _whale_summary),
    "etf": _CategorySpec(EtfFlowSnapshot, "computed_at", _etf_summary),
    "sentiment": _CategorySpec(SentimentSnapshot, "computed_at", _sentiment_summary),
    "global_score": _CategorySpec(GlobalMarketScore, "computed_at", _global_score_summary),
    "news": _CategorySpec(NewsItem, "fetched_at", _news_summary),
    "macro_events": _CategorySpec(HistoricalEvent, "event_date", _macro_events_summary),
    "alerts": _CategorySpec(AlertLog, "triggered_at", _alerts_summary),
}

CATEGORY_NAMES: tuple[str, ...] = tuple(_CATEGORIES)


class MemoryEngine:
    """Read-only aggregation across every persisted history table."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_category(
        self, category: str, limit: int = 20, since: datetime | None = None
    ) -> list[dict]:
        spec = _CATEGORIES.get(category)
        if spec is None:
            raise ValueError(f"Unknown memory category: {category}. Valid: {CATEGORY_NAMES}")

        timestamp_col = getattr(spec.model, spec.timestamp_column)
        query = select(spec.model).order_by(timestamp_col.desc()).limit(limit)
        if since is not None:
            query = query.where(timestamp_col >= since)

        async with self._session_factory() as session:
            rows = list(await session.scalars(query))

        return [
            {
                "category": category,
                "timestamp": getattr(row, spec.timestamp_column).isoformat(),
                "summary": spec.serialize(row),
            }
            for row in rows
        ]

    async def get_timeline(
        self,
        categories: list[str] | None = None,
        limit: int = 50,
        since: datetime | None = None,
    ) -> list[dict]:
        selected = categories or list(CATEGORY_NAMES)
        entries: list[dict] = []
        for category in selected:
            entries.extend(await self.get_category(category, limit=limit, since=since))
        entries.sort(key=lambda e: e["timestamp"], reverse=True)
        return entries[:limit]
