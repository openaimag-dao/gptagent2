import json
import logging
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import (
    AssetPrice,
    Correlation,
    MarketRegimeSnapshot,
    NewsItem,
    Report,
    SignalSnapshot,
)
from app.llm.client import get_llm_client
from app.services.analysis.correlation import CorrelationEngine
from app.services.analysis.regime import MarketRegime, RegimeDetector
from app.services.analysis.schemas import AIAnalysisContent
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.signals.engine import SignalEngine

logger = logging.getLogger(__name__)

# Symbols worth summarizing in every report, in display order.
_KEY_SYMBOLS: tuple[str, ...] = (
    "BTC", "ETH", "SOL", "TOTAL", "BTC.D",
    "NASDAQ", "SPX", "DJI", "RUT",
    "DXY", "GOLD", "SILVER", "OIL", "VIX", "US10Y", "US30Y", "FEDRATE",
)

_HIGH_RISK_REGIMES = frozenset(
    {MarketRegime.RISK_OFF, MarketRegime.FLIGHT_TO_SAFETY, MarketRegime.LIQUIDITY_CONTRACTION}
)
_LOW_RISK_REGIMES = frozenset({MarketRegime.RISK_ON, MarketRegime.LIQUIDITY_EXPANSION})

SYSTEM_PROMPT = """You are a senior macro and crypto market analyst, in the style of a \
Bloomberg Terminal / Glassnode / institutional research desk. You are given real, \
already-computed market data, recent news, asset correlations, a detected market regime, \
and a bull/bear signal score.

Your job is to explain WHY markets are moving -- never simply state that an asset went up \
or down. Ground every claim in the data provided below. If a section's underlying data is \
unavailable, say so explicitly (e.g. "US Treasury yield data was unavailable this cycle") \
rather than inventing detail.

Respond with a single JSON object with exactly these fields (all strings except the three \
probability fields, which are integers 0-100 that must sum to 100):
{
  "what_changed": "...",
  "why": "...",
  "who_is_driving": "...",
  "institutional_behavior": "...",
  "macro_explanation": "...",
  "historical_comparison": "...",
  "main_risks": "...",
  "key_events_today": "...",
  "probability_bullish_pct": 0,
  "probability_bearish_pct": 0,
  "probability_neutral_pct": 0
}"""


def derive_risk_level(regime: MarketRegime) -> str:
    if regime in _HIGH_RISK_REGIMES:
        return "high"
    if regime in _LOW_RISK_REGIMES:
        return "low"
    return "moderate"


def _format_market_lines(assets: list[AssetPrice]) -> list[str]:
    by_symbol = {a.symbol: a for a in assets}
    lines = []
    for symbol in _KEY_SYMBOLS:
        asset = by_symbol.get(symbol)
        if asset is None:
            lines.append(f"- {symbol}: not available")
            continue
        change = f"{asset.change_pct_24h:+.2f}%" if asset.change_pct_24h is not None else "n/a"
        lines.append(f"- {symbol}: {float(asset.price):,.2f} ({change} 24h)")
    return lines


def _format_news_lines(news: list[NewsItem]) -> list[str]:
    if not news:
        return ["- No recent news available."]
    return [
        f"- [{item.category.value}] ({item.sentiment.value}) {item.title} -- {item.source}"
        for item in news
    ]


def _format_correlation_lines(correlations: list[Correlation]) -> list[str]:
    if not correlations:
        return ["- No correlation data available yet."]
    return [
        f"- {c.symbol_a}/{c.symbol_b} ({c.window_days}d): {float(c.correlation):+.2f}"
        for c in correlations
    ]


def build_user_prompt(
    assets: list[AssetPrice],
    news: list[NewsItem],
    correlations: list[Correlation],
    regime_snapshot: MarketRegimeSnapshot,
    signal_snapshot: SignalSnapshot,
) -> str:
    """Builds the LLM user prompt from already-computed, real data. Pure and unit-testable."""
    return "\n\n".join(
        [
            "MARKET SNAPSHOT",
            "\n".join(_format_market_lines(assets)),
            "DETECTED MARKET REGIME",
            f"- Regime: {regime_snapshot.regime.value}",
            f"- Inputs: {json.dumps(regime_snapshot.inputs)}",
            "BULL/BEAR SIGNAL SCORE",
            (
                f"- Bull score: {signal_snapshot.bull_score}, "
                f"Bear score: {signal_snapshot.bear_score}, "
                f"Net: {signal_snapshot.net_score}, "
                f"Confidence: {signal_snapshot.confidence_pct}%"
            ),
            f"- Factor breakdown: {json.dumps(signal_snapshot.factors)}",
            "ROLLING CORRELATIONS",
            "\n".join(_format_correlation_lines(correlations)),
            "RECENT NEWS (most recent first)",
            "\n".join(_format_news_lines(news)),
        ]
    )


class ReportGenerator:
    """Gathers every analysis engine's latest output and asks the LLM to explain WHY."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        market_repository: MarketRepository,
        news_repository: NewsRepository,
        correlation_engine: CorrelationEngine,
        regime_detector: RegimeDetector,
        signal_engine: SignalEngine,
    ) -> None:
        self._session_factory = session_factory
        self._market_repository = market_repository
        self._news_repository = news_repository
        self._correlation_engine = correlation_engine
        self._regime_detector = regime_detector
        self._signal_engine = signal_engine

    async def generate_and_store(self, report_type: str = "scheduled") -> Report:
        assets = await self._market_repository.get_latest()
        news = await self._news_repository.get_recent(limit=15)
        correlations = await self._correlation_engine.get_latest()
        regime_snapshot = await self._regime_detector.get_latest()
        signal_snapshot = await self._signal_engine.get_latest()

        if regime_snapshot is None or signal_snapshot is None:
            raise RuntimeError(
                "Cannot generate a report before regime detection and signal scoring "
                "have run at least once"
            )

        user_prompt = build_user_prompt(
            assets, news, correlations, regime_snapshot, signal_snapshot
        )

        settings = get_settings()
        client = get_llm_client()
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        raw_content = response.choices[0].message.content or ""

        try:
            analysis = AIAnalysisContent.model_validate(json.loads(raw_content))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(f"LLM returned an invalid analysis payload: {exc}") from exc

        market_summary: dict[str, Any] = {
            a.symbol: {
                "price": float(a.price),
                "change_pct_24h": float(a.change_pct_24h) if a.change_pct_24h is not None else None,
            }
            for a in assets
            if a.symbol in _KEY_SYMBOLS
        }
        correlations_summary = [
            {
                "pair": f"{c.symbol_a}/{c.symbol_b}",
                "window_days": c.window_days,
                "correlation": float(c.correlation),
            }
            for c in correlations
        ]

        report = Report(
            id=uuid.uuid4(),
            report_type=report_type,
            regime=regime_snapshot.regime.value,
            risk_level=derive_risk_level(regime_snapshot.regime),
            bull_score=signal_snapshot.bull_score,
            bear_score=signal_snapshot.bear_score,
            confidence_pct=signal_snapshot.confidence_pct,
            market_summary=market_summary,
            correlations_summary=correlations_summary,
            analysis=analysis.model_dump(),
        )

        async with self._session_factory() as session:
            session.add(report)
            await session.commit()
            await session.refresh(report)
        return report

    async def get_latest(self) -> Report | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(Report).order_by(Report.generated_at.desc()).limit(1)
            )
