"""Futures Simulator -- periodic resting-order fills (LIMIT / STOP_MARKET
/ TAKE_PROFIT_MARKET). Same 100% demo/paper-trading scope as orders.py:
no real orders are ever placed on any real exchange.

Runs on a schedule (see app.scheduler.jobs.fill_futures_sim_orders_job)
for the same reason app.services.futures_sim.monitor does: a resting
order can cross its trigger price purely from a market move, with no
further action from the user.

Deterministic fill model (task's own stated preference over an
unrealistic partial-fill simulation): a resting order either fills
completely, once the current price crosses its trigger price favorably,
or stays NEW. Never PARTIALLY_FILLED."""

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import FuturesSimAccount, FuturesSimOrder
from app.services.futures_sim.engine import (
    compute_fee,
    compute_market_fill_price,
    get_current_price,
)
from app.services.futures_sim.orders import OrderRejected, _open_position_for_symbol, execute_fill

_RESTING_ORDER_TYPES = ("LIMIT", "STOP_MARKET", "TAKE_PROFIT_MARKET")


def _should_fill(order: FuturesSimOrder, current_price: float) -> bool:
    """Pure function: has this resting order's trigger price been crossed
    favorably?

    LIMIT triggers against `order.price` (the guaranteed fill price): a
    BUY LIMIT wants to buy at or below its price, a SELL LIMIT wants to
    sell at or above it.

    STOP_MARKET/TAKE_PROFIT_MARKET trigger against `order.stop_price` in
    the OPPOSITE direction from LIMIT -- both order types use the
    identical trigger direction as each other (they only differ in
    intended use, matching real exchange semantics): a BUY triggers once
    price has risen to or above the stop price, a SELL once it has fallen
    to or below it."""
    if order.order_type == "LIMIT":
        trigger_price = float(order.price)
        return (
            current_price <= trigger_price
            if order.side == "BUY"
            else current_price >= trigger_price
        )
    trigger_price = float(order.stop_price)
    return current_price >= trigger_price if order.side == "BUY" else current_price <= trigger_price


def _fill_reference(order: FuturesSimOrder, current_price: float) -> dict:
    """A LIMIT fill happens at exactly its own price (no slippage -- that
    guarantee is the entire point of a limit order). A triggered
    STOP_MARKET/TAKE_PROFIT_MARKET is, from the trigger moment on, a
    genuine market order and fills with slippage against the current
    price, same as any other MARKET fill (§3 of docs/FUTURES_SIMULATOR_MATH.md)."""
    if order.order_type == "LIMIT":
        price = float(order.price)
        return {
            "requested_price": price,
            "estimated_fill_price": price,
            "actual_fill_price": price,
            "slippage_pct": 0.0,
        }
    return compute_market_fill_price(order.side, current_price)


async def check_resting_orders_for_fills(
    session_factory: async_sessionmaker[AsyncSession], redis: Redis
) -> list[dict]:
    """Scans every status=NEW LIMIT/STOP_MARKET/TAKE_PROFIT_MARKET order
    and fills any whose trigger price has been crossed, via the same
    execute_fill() path place_market_order uses for an immediate MARKET
    fill -- an order filled this way produces the identical position/
    trade/ledger effects a MARKET order placed at that instant would.
    Returns one dict per fill for logging/observability."""
    async with session_factory() as session:
        orders = list(
            await session.scalars(
                select(FuturesSimOrder).where(
                    FuturesSimOrder.status == "NEW",
                    FuturesSimOrder.order_type.in_(_RESTING_ORDER_TYPES),
                )
            )
        )

    filled = []
    for candidate in orders:
        price_info = await get_current_price(session_factory, redis, candidate.symbol)
        if price_info is None:
            continue
        current_price = price_info["price"]
        if not _should_fill(candidate, current_price):
            continue

        async with session_factory() as session:
            # Re-fetch inside this session (never mutate `candidate`,
            # which belongs to the closed scan session above) and
            # re-check status=NEW -- a concurrent cancel or a duplicate
            # scheduler tick could have already resolved this order.
            order = await session.get(FuturesSimOrder, candidate.id)
            account = await session.get(FuturesSimAccount, candidate.account_id)
            if order is None or order.status != "NEW" or account is None:
                continue

            fill = _fill_reference(order, current_price)
            fee_info = compute_fee(
                float(order.quantity) * fill["actual_fill_price"], is_maker=False
            )
            order.requested_price = fill["requested_price"]
            order.estimated_fill_price = fill["estimated_fill_price"]
            order.actual_fill_price = fill["actual_fill_price"]
            order.slippage_pct = fill["slippage_pct"]
            order.fee_rate_pct = fee_info["fee_rate_pct"]
            order.fee_amount = fee_info["fee_amount"]

            position = await _open_position_for_symbol(session, account.id, order.symbol)
            try:
                await execute_fill(
                    session,
                    session_factory,
                    redis,
                    account,
                    order,
                    position,
                    symbol=order.symbol,
                    side=order.side,
                    quantity=float(order.quantity),
                    leverage=order.leverage,
                    margin_mode=order.margin_mode,
                    reduce_only=order.reduce_only,
                    fill=fill,
                    fee_info=fee_info,
                )
            except OrderRejected:
                # e.g. insufficient margin by fill time, or a reduceOnly
                # order with nothing left to reduce -- the order is left
                # REJECTED by execute_fill/its callees, not silently
                # dropped, and simply isn't reported as a fill here.
                continue

        filled.append(
            {"order_id": order.id, "symbol": order.symbol, "order_type": order.order_type}
        )
    return filled
