"""Futures Simulator -- periodic position monitoring for liquidation and
SL/TP triggers. Same 100% demo/paper-trading scope as engine.py/orders.py:
this only auto-closes simulated positions in the futures_sim_* tables,
never touches a real exchange.

Runs on a schedule (see app.scheduler.jobs.check_futures_sim_positions_job)
rather than being invoked per-request, since a position can be liquidated
or hit its SL/TP purely from a price move with no order ever placed by the
user."""

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import FuturesSimAccount, FuturesSimPosition
from app.services.futures_sim.engine import get_current_price
from app.services.futures_sim.orders import OrderRejected, close_position


def _determine_trigger(position: FuturesSimPosition, mark_price: float) -> str | None:
    """Pure function: which trigger (if any) this mark price has crossed
    for this position. Priority LIQUIDATION > STOP_LOSS > TAKE_PROFIT --
    liquidation is the most severe possible outcome and always wins if a
    position has somehow crossed multiple triggers on the same check."""
    liq = float(position.liquidation_price) if position.liquidation_price is not None else None
    sl = float(position.sl_price) if position.sl_price is not None else None
    tp = float(position.tp_price) if position.tp_price is not None else None

    if position.side == "LONG":
        if liq is not None and mark_price <= liq:
            return "LIQUIDATION"
        if sl is not None and mark_price <= sl:
            return "STOP_LOSS"
        if tp is not None and mark_price >= tp:
            return "TAKE_PROFIT"
    else:  # SHORT
        if liq is not None and mark_price >= liq:
            return "LIQUIDATION"
        if sl is not None and mark_price >= sl:
            return "STOP_LOSS"
        if tp is not None and mark_price <= tp:
            return "TAKE_PROFIT"
    return None


async def check_positions_for_triggers(
    session_factory: async_sessionmaker[AsyncSession], redis: Redis
) -> list[dict]:
    """Scans every OPEN position (across every account, active or not --
    an account being RESET doesn't erase its still-open positions, see
    FuturesSimEngine.reset_account's own docstring) and closes any whose
    current mark price has crossed its liquidation price, stop-loss, or
    take-profit via the same close_position() primitive a manual close
    uses, just with exit_reason set to whichever trigger fired. Returns
    one dict per closure for logging/observability."""
    async with session_factory() as session:
        positions = list(
            await session.scalars(
                select(FuturesSimPosition).where(FuturesSimPosition.status == "OPEN")
            )
        )

    closures = []
    for position in positions:
        price_info = await get_current_price(session_factory, redis, position.symbol)
        if price_info is None:
            continue
        trigger = _determine_trigger(position, price_info["price"])
        if trigger is None:
            continue

        async with session_factory() as session:
            account = await session.get(FuturesSimAccount, position.account_id)
        if account is None:
            continue

        try:
            trade = await close_position(
                account, session_factory, redis, position_id=position.id, exit_reason=trigger
            )
        except OrderRejected:
            # Already closed (or otherwise no longer eligible) by a
            # concurrent manual close between the scan above and this
            # attempt -- not an error, just nothing left to do.
            continue

        closures.append(
            {
                "position_id": position.id,
                "account_id": account.id,
                "symbol": position.symbol,
                "exit_reason": trigger,
                "net_pnl": float(trade.net_pnl),
            }
        )
    return closures
