import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import (
    AssetClass,
    AssetPrice,
    CryptoHistory,
    MacroHistory,
    MarketHistory,
    SimilarMarketMatch,
)
from app.services.analysis.regime import MarketRegime, detect_regime
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.knowledge.analysis import find_similar_episodes
from app.services.probability.engine import compute_forward_returns

logger = logging.getLogger(__name__)

_MIN_HISTORY_LENGTH = 30
_DEFAULT_K = 25
_FORWARD_HORIZONS = (1, 3, 7, 30)

# Symbols detect_regime() needs to reconstruct a historical regime tag for a
# past date -- reused as-is, never reimplemented, so a historical regime tag
# means exactly the same thing as a live one.
_REGIME_SYMBOL_TABLES: dict[str, type] = {
    "SPX": MarketHistory,
    "BTC": CryptoHistory,
    "VIX": MacroHistory,
    "DXY": MacroHistory,
    "GOLD": MacroHistory,
    "US10Y": MacroHistory,
    "FEDRATE": MacroHistory,
}
_REGIME_SYMBOL_ASSET_CLASS: dict[str, AssetClass] = {
    "SPX": AssetClass.INDEX,
    "BTC": AssetClass.CRYPTO,
    "VIX": AssetClass.MACRO,
    "DXY": AssetClass.MACRO,
    "GOLD": AssetClass.MACRO,
    "US10Y": AssetClass.MACRO,
    "FEDRATE": AssetClass.MACRO,
}


async def _build_regime_index(
    session_factory: async_sessionmaker[AsyncSession], timeframe: Timeframe
) -> dict[str, dict]:
    """{symbol: {timestamp: history_row}} for every symbol detect_regime() needs.
    Missing symbols (not yet synced) are simply absent -- degrades to a lower
    regime-reconstruction rate rather than failing outright."""
    index: dict[str, dict] = {}
    for symbol, model in _REGIME_SYMBOL_TABLES.items():
        try:
            rows = await get_series(session_factory, model, symbol, timeframe)
        except Exception:
            rows = []
        index[symbol] = {r.timestamp: r for r in rows}
    return index


def _reconstruct_regime_at(regime_index: dict[str, dict], timestamp) -> MarketRegime | None:
    assets = []
    for symbol in _REGIME_SYMBOL_TABLES:
        row = regime_index.get(symbol, {}).get(timestamp)
        if row is None or row.return_pct is None:
            continue
        return_pct = float(row.return_pct)
        change_pct = return_pct * 100
        change_abs = return_pct * float(row.close)
        assets.append(
            AssetPrice(
                symbol=symbol,
                name=symbol,
                asset_class=_REGIME_SYMBOL_ASSET_CLASS[symbol],
                price=row.close,
                change_pct_24h=change_pct,
                change_24h=change_abs,
                source="history_reconstruction",
            )
        )
    # detect_regime's rules need at least the risk-on/off quartet to say
    # anything more specific than "not enough data" -- below that, be honest
    # and return None rather than a low-confidence guess.
    if len(assets) < 4:
        return None
    regime, _ = detect_regime(assets)
    return regime


class SimilarMarketEngine:
    """Finds the K most similar historical periods to a symbol's current
    conditions and reports what happened 1/3/7/30 periods later, plus (where
    reconstructible) the historical market regime and BTC/NASDAQ's own move
    that day -- extends the Sprint 3 Knowledge Engine's analog search rather
    than duplicating it.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_similar_periods(
        self,
        symbol: str,
        model: type,
        timeframe: Timeframe = Timeframe.DAILY,
        k: int = _DEFAULT_K,
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

        regime_index = await _build_regime_index(self._session_factory, timeframe)
        btc_index = regime_index["BTC"] if symbol != "BTC" else {r.timestamp: r for r in rows}
        nasdaq_index = regime_index["SPX"]

        # Similarity score: invert the z-score distance into a bounded 0-100
        # read (closer historical episode -> higher score). Distances are
        # unbounded in principle, so this saturates rather than going negative.
        matches = []
        for episode in episodes:
            idx = episode["index"]
            distance = episode["distance"]
            similarity = round(100 / (1 + distance), 1)
            regime = _reconstruct_regime_at(regime_index, episode["timestamp"])
            btc_row = btc_index.get(episode["timestamp"])
            nasdaq_row = nasdaq_index.get(episode["timestamp"])

            matches.append(
                {
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
            )
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
