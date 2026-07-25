import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import HistoricalEvent
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.knowledge.analysis import find_similar_episodes
from app.services.probability.engine import compute_forward_returns

logger = logging.getLogger(__name__)

_MIN_HISTORY_LENGTH = 30
_DEFAULT_FORWARD_HORIZON = 5
_DEFAULT_EVENT_WINDOW_DAYS = 14


class KnowledgeEngine:
    """Finds real historical episodes similar to a symbol's current conditions.

    This is what grounds the AI report's "historical comparison" in actual
    data instead of LLM improvisation: it surfaces real past dates with
    similar RSI/volatility, what actually happened next (forward return),
    and any curated historical event nearby -- the LLM is then told to work
    from this, not to invent a comparison.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def _all_events(self) -> list[HistoricalEvent]:
        async with self._session_factory() as session:
            return list(
                await session.scalars(select(HistoricalEvent).order_by(HistoricalEvent.event_date))
            )

    async def find_analogs(
        self,
        symbol: str,
        model: type,
        timeframe: Timeframe = Timeframe.DAILY,
        k: int = 5,
        forward_horizon: int = _DEFAULT_FORWARD_HORIZON,
        event_window_days: int = _DEFAULT_EVENT_WINDOW_DAYS,
    ) -> list[dict]:
        rows = await get_series(self._session_factory, model, symbol, timeframe)
        if len(rows) < _MIN_HISTORY_LENGTH:
            return []

        rsi_series = [float(r.rsi) if r.rsi is not None else None for r in rows]
        volatility_series = [
            float(r.volatility) if r.volatility is not None else None for r in rows
        ]
        returns_series = [float(r.return_pct) if r.return_pct is not None else None for r in rows]
        timestamps = [r.timestamp for r in rows]

        current_rsi = rsi_series[-1]
        if current_rsi is None:
            return []

        episodes = find_similar_episodes(
            rsi_series, volatility_series, timestamps, current_rsi, volatility_series[-1], k=k
        )
        forward_returns = compute_forward_returns(returns_series, horizon=forward_horizon)
        events = await self._all_events()
        window = timedelta(days=event_window_days)

        analogs = []
        for episode in episodes:
            forward = forward_returns[episode["index"]]
            nearby = [
                {"title": e.title, "event_date": e.event_date.isoformat()}
                for e in events
                if abs(e.event_date - episode["timestamp"]) <= window
            ]
            analogs.append(
                {
                    "timestamp": episode["timestamp"],
                    "rsi": episode["rsi"],
                    "volatility": episode["volatility"],
                    "distance": round(episode["distance"], 3),
                    "forward_return_pct": (
                        round(forward * 100, 2) if forward is not None else None
                    ),
                    "nearby_events": nearby,
                }
            )
        return analogs


def build_grounding_text(symbol: str, analogs: list[dict]) -> str:
    """Formats analogs into plain text for the LLM prompt -- real dates, real
    outcomes, real events, nothing invented."""
    if not analogs:
        return f"- No sufficiently similar historical episode found for {symbol}."

    lines = [f"- {symbol} conditions today most resemble:"]
    for analog in analogs:
        date_str = analog["timestamp"].date().isoformat()
        forward = analog["forward_return_pct"]
        forward_str = f"{forward:+.2f}%" if forward is not None else "n/a"
        line = f"  - {date_str} (RSI {analog['rsi']:.1f}): next-period return was {forward_str}"
        if analog["nearby_events"]:
            titles = ", ".join(e["title"] for e in analog["nearby_events"])
            line += f" -- nearby event(s): {titles}"
        lines.append(line)
    return "\n".join(lines)
