import logging
from collections import Counter
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import HistoricalEvent, SimilarMarketMatch
from app.services.analysis.regime import build_regime_index, reconstruct_regime_at
from app.services.backtest.metrics import compute_backtest_metrics, compute_win_rate_pct
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.knowledge.analysis import find_similar_episodes
from app.services.probability.engine import compute_forward_returns

logger = logging.getLogger(__name__)

_MIN_HISTORY_LENGTH = 30
_DEFAULT_K = 25
_FORWARD_HORIZONS = (1, 3, 7, 30)
_DEFAULT_EVENT_WINDOW_DAYS = 14


# The forward horizon "Average outcome"/"Probability" answer -- 7 trading
# periods balances enough matches surviving (30d often thins out near the
# end of a history series) against being a meaningful holding period.
_LESSON_HORIZON = 7


def build_historical_lesson(symbol: str, matches: list[dict]) -> dict | None:
    """Composes find_similar_periods()/find_and_store() output into a
    plain-language lesson -- what happened, how similar, average outcome,
    probability, typical duration, main lesson -- for v8.0's "Replay should
    explain history, not just store it." Every field is derived from the K
    matches already computed by SimilarMarketEngine; no new external calls,
    no fabricated numbers. Returns None when there isn't enough data to say
    anything trustworthy.
    """
    if not matches:
        return None

    primary_key = f"{_LESSON_HORIZON}d"
    primary_returns = [
        m["forward_returns_pct"][primary_key] / 100
        for m in matches
        if m["forward_returns_pct"].get(primary_key) is not None
    ]
    metrics = compute_backtest_metrics(primary_returns)
    if metrics is None:
        return None

    avg_similarity = round(sum(m["similarity"] for m in matches) / len(matches), 1)
    direction = "up" if metrics["avg_return_pct"] >= 0 else "down"

    regimes = [m["market_regime"] for m in matches if m["market_regime"] is not None]
    dominant_regime = Counter(regimes).most_common(1)[0][0] if regimes else None

    # "Typical duration": the longest tested horizon (1d/3d/7d/30d) across
    # which a majority of matches kept moving in the same direction as the
    # primary-horizon average -- a persistence read derived from the same
    # forward-return data, not a new signal.
    persistence_days = None
    for horizon in _FORWARD_HORIZONS:
        horizon_returns = [
            m["forward_returns_pct"][f"{horizon}d"] / 100
            for m in matches
            if m["forward_returns_pct"].get(f"{horizon}d") is not None
        ]
        if not horizon_returns:
            break
        agreement = [r if direction == "up" else -r for r in horizon_returns]
        win_rate = compute_win_rate_pct(agreement)
        if win_rate is None or win_rate < 50.0:
            break
        persistence_days = horizon

    what_happened = f"{metrics['occurrences']} similar historical setups found for {symbol}"
    if dominant_regime is not None:
        what_happened += f", most often during a {dominant_regime.replace('_', ' ')} regime"
    what_happened += "."

    if persistence_days is not None:
        typical_duration = (
            f"The {direction}ward move tended to hold for at least {persistence_days} "
            "day(s) in similar past cases."
        )
    else:
        typical_duration = "No consistent persistence pattern across the tested horizons."

    main_lesson = (
        f"In similar setups (avg similarity {avg_similarity}%), {symbol} moved {direction} "
        f"{abs(metrics['avg_return_pct'])}% on average over the next {_LESSON_HORIZON} days, "
        f"with a {metrics['win_rate_pct']}% historical win rate across {metrics['occurrences']} "
        "occurrences."
    )

    return {
        "symbol": symbol,
        "occurrences": metrics["occurrences"],
        "horizon_days": _LESSON_HORIZON,
        "what_happened": what_happened,
        "how_similar_pct": avg_similarity,
        "average_outcome_pct": metrics["avg_return_pct"],
        "probability_pct": metrics["win_rate_pct"],
        "typical_duration": typical_duration,
        "dominant_regime": dominant_regime,
        "main_lesson": main_lesson,
    }


class SimilarMarketEngine:
    """Finds the K most similar historical periods to a symbol's current
    conditions and reports what happened 1/3/7/30 periods later, plus (where
    reconstructible) the historical market regime and BTC/NASDAQ's own move
    that day. v12.0 P2 -- also absorbs the Sprint 3 Knowledge Engine's only
    unique value (curated nearby-event lookup, opt-in via
    `include_nearby_events`) since both engines ran the identical RSI/
    volatility distance search (`find_similar_episodes`) against the same
    series independently; this is now the one place that search runs.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def _all_events(self) -> list[HistoricalEvent]:
        async with self._session_factory() as session:
            return list(
                await session.scalars(select(HistoricalEvent).order_by(HistoricalEvent.event_date))
            )

    async def find_similar_periods(
        self,
        symbol: str,
        model: type,
        timeframe: Timeframe = Timeframe.DAILY,
        k: int = _DEFAULT_K,
        include_nearby_events: bool = False,
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
        forward_by_horizon = {
            h: compute_forward_returns(returns_series, horizon=h) for h in _FORWARD_HORIZONS
        }

        regime_index = await build_regime_index(self._session_factory, timeframe)
        btc_index = regime_index["BTC"] if symbol != "BTC" else {r.timestamp: r for r in rows}
        nasdaq_index = regime_index["SPX"]

        # Nearby-event lookup (ex-Knowledge Engine): fetched once per call,
        # not once per match, and only when a caller actually wants to
        # display it -- the many machine-consumption callers (Explanation/
        # Watchdog/Replay/Terminal) never pass this, so they pay no extra
        # query for a field they never read.
        events = await self._all_events() if include_nearby_events else []
        window = timedelta(days=event_window_days)

        # Similarity score: invert the z-score distance into a bounded 0-100
        # read (closer historical episode -> higher score). Distances are
        # unbounded in principle, so this saturates rather than going negative.
        matches = []
        for episode in episodes:
            idx = episode["index"]
            distance = episode["distance"]
            similarity = round(100 / (1 + distance), 1)
            regime = reconstruct_regime_at(regime_index, episode["timestamp"])
            btc_row = btc_index.get(episode["timestamp"])
            nasdaq_row = nasdaq_index.get(episode["timestamp"])

            match = {
                "date": episode["timestamp"],
                "similarity": similarity,
                "market_regime": regime.value if regime is not None else None,
                "rsi": episode["rsi"],
                "volatility": episode["volatility"],
                "btc_result_pct": (
                    round(float(btc_row.return_pct) * 100, 2)
                    if btc_row is not None and btc_row.return_pct is not None
                    else None
                ),
                "nasdaq_result_pct": (
                    round(float(nasdaq_row.return_pct) * 100, 2)
                    if nasdaq_row is not None and nasdaq_row.return_pct is not None
                    else None
                ),
                "forward_returns_pct": {
                    f"{h}d": (
                        round(forward_by_horizon[h][idx] * 100, 2)
                        if forward_by_horizon[h][idx] is not None
                        else None
                    )
                    for h in _FORWARD_HORIZONS
                },
            }
            if include_nearby_events:
                match["nearby_events"] = [
                    {"title": e.title, "event_date": e.event_date.isoformat()}
                    for e in events
                    if abs(e.event_date - episode["timestamp"]) <= window
                ]
            matches.append(match)
        return matches

    async def find_and_store(
        self,
        symbol: str,
        model: type,
        timeframe: Timeframe = Timeframe.DAILY,
        k: int = _DEFAULT_K,
    ) -> list[dict]:
        """Same as find_similar_periods, but persists every comparison to
        similar_market_matches for later audit/review."""
        matches = await self.find_similar_periods(symbol, model, timeframe, k)
        if not matches:
            return matches

        rows = await get_series(self._session_factory, model, symbol, timeframe)
        reference_timestamp = rows[-1].timestamp

        db_rows = [
            SimilarMarketMatch(
                symbol=symbol,
                timeframe=timeframe.value,
                reference_timestamp=reference_timestamp,
                match_timestamp=m["date"],
                similarity_score=m["similarity"],
                market_regime=m["market_regime"],
                btc_result_pct=m["btc_result_pct"],
                nasdaq_result_pct=m["nasdaq_result_pct"],
                forward_return_1d_pct=m["forward_returns_pct"]["1d"],
                forward_return_3d_pct=m["forward_returns_pct"]["3d"],
                forward_return_7d_pct=m["forward_returns_pct"]["7d"],
                forward_return_30d_pct=m["forward_returns_pct"]["30d"],
            )
            for m in matches
        ]
        async with self._session_factory() as session:
            session.add_all(db_rows)
            await session.commit()
        return matches
