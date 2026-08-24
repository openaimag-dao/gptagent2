"""Futures Simulator -- funding. Same 100% demo/paper-trading scope as
engine.py/orders.py: no real money changes hands, this only debits/
credits the account's own simulated wallet_balance.

Real funding rate (task: "Funding using real data if available else
'unavailable'") comes from the same WhaleIntelligenceEngine derivatives
snapshot the Whale Intelligence page already uses (CoinGlass primary,
CoinGecko derivatives fallback) -- no new market-data integration. When
neither source has a rate for a symbol, a configured SIMULATED fallback
rate is used instead, and every ledger entry it produces is explicitly
labeled SIMULATED, never presented as real."""

from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import FuturesSimAccount, FuturesSimLedgerEntry, FuturesSimPosition
from app.services.whales.engine import WhaleIntelligenceEngine


async def _funding_rate_info(symbol: str) -> dict:
    """Real funding rate for `symbol`, expressed as a PERCENT (e.g. 0.01
    means 0.01%) to match every other *_pct field in this codebase.
    CoinGlass/CoinGecko's `funding_rate` field is already a percentage,
    not a fraction -- verified directly against CoinGecko's live
    `/derivatives` response for Binance's BTCUSDT perpetual (funding_rate
    0.007731 corresponds to Binance's own displayed 0.0077% funding, not
    0.7731%), so no unit conversion happens here. Falls back to the
    configured SIMULATED rate, clearly labeled, when no real source has
    data for this symbol -- never a fabricated real-looking number."""
    settings = get_settings()
    try:
        snapshot = await WhaleIntelligenceEngine().get_snapshot(symbol)
    except Exception:
        snapshot = {}
    raw = snapshot.get("funding_rate")
    if raw is not None:
        return {"funding_rate_pct": float(raw), "source": "real", "label": "real"}
    return {
        "funding_rate_pct": settings.futures_sim_simulated_funding_rate_pct,
        "source": "simulated",
        "label": "SIMULATED",
    }


async def apply_funding_to_open_positions(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,  # noqa: ARG001 -- kept for signature parity with the other
    # scheduled futures_sim jobs (monitor.py, resting_orders.py);
    # WhaleIntelligenceEngine manages its own Redis cache internally.
) -> list[dict]:
    """Charges (or pays, when the rate is negative) funding to every OPEN
    position, once per call -- the scheduler decides the cadence
    (app.scheduler.jobs.apply_futures_sim_funding_job, every
    futures_sim_funding_interval_hours, matching real exchanges' 8-hour
    settlement). LONG pays when the rate is positive (mirrors real
    exchange convention: longs pay shorts when funding is positive);
    SHORT is the exact mirror. Returns one dict per position charged, for
    logging/observability."""
    async with session_factory() as session:
        positions = list(
            await session.scalars(
                select(FuturesSimPosition).where(FuturesSimPosition.status == "OPEN")
            )
        )

    charged = []
    rate_cache: dict[str, dict] = {}
    for position in positions:
        if position.symbol not in rate_cache:
            rate_cache[position.symbol] = await _funding_rate_info(position.symbol)
        rate_info = rate_cache[position.symbol]

        notional = float(position.quantity) * float(position.mark_price)
        funding_fee = notional * rate_info["funding_rate_pct"] / 100
        signed_fee = funding_fee if position.side == "LONG" else -funding_fee

        async with session_factory() as session:
            # Re-bind to this session's own copies before mutating --
            # `position` came from the scan session above, which has
            # already closed (see the matching comment in orders.py).
            account = await session.get(FuturesSimAccount, position.account_id)
            db_position = await session.get(FuturesSimPosition, position.id)
            if account is None or db_position is None or db_position.status != "OPEN":
                continue

            account.wallet_balance = float(account.wallet_balance) - signed_fee
            account.funding_paid_total = float(account.funding_paid_total) + signed_fee
            db_position.funding_paid = float(db_position.funding_paid) + signed_fee
            db_position.updated_at = datetime.now(UTC)

            session.add(
                FuturesSimLedgerEntry(
                    account_id=account.id,
                    event_type="FUNDING",
                    amount=-signed_fee,
                    balance_after=float(account.wallet_balance),
                    reference_type="POSITION",
                    reference_id=db_position.id,
                    description=(
                        f"{rate_info['label']} funding on {db_position.symbol} "
                        f"{db_position.side}: rate {rate_info['funding_rate_pct']:+.4f}%, "
                        f"fee {signed_fee:+.8f}"
                    ),
                )
            )
            await session.commit()

        charged.append(
            {
                "position_id": position.id,
                "symbol": position.symbol,
                "funding_rate_pct": rate_info["funding_rate_pct"],
                "source": rate_info["source"],
                "signed_fee": signed_fee,
            }
        )
    return charged
