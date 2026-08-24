"""Futures Simulator -- order execution (open/increase/reduce/close a
position). Same 100% demo/paper-trading scope as engine.py: no real money,
no real exchange orders. Kept separate from engine.py (account lifecycle +
pure math) so this file stays a single, auditable source of truth for
"what happens when an order is placed," while engine.py stays the source of
truth for "how is a number computed."

ONE-WAY position mode only (task requirement for the first production
implementation): each (account, symbol) has at most one open position at a
time. A market order against an existing position either increases it (same
direction), reduces/closes it (opposite direction, quantity <= position
size), or "flips" it (opposite direction, quantity > position size, and NOT
reduce_only -- closes the existing position fully and opens a new one in the
new direction with the remainder), matching real one-way-mode semantics.

Idempotency (task requirement): every order carries a `client_order_id`; a
second call with the same id returns the already-existing order unchanged,
never double-executing from a double click / network retry / duplicate
WebSocket event.
"""

import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import (
    FuturesSimAccount,
    FuturesSimLedgerEntry,
    FuturesSimOrder,
    FuturesSimPosition,
    FuturesSimTrade,
)
from app.services.futures_sim.engine import (
    compute_cross_liquidation_price,
    compute_fee,
    compute_initial_margin,
    compute_isolated_liquidation_price,
    compute_maintenance_margin,
    compute_market_fill_price,
    compute_net_pnl,
    compute_position_pnl,
    compute_roi_pct,
    get_current_price,
    resolve_maintenance_margin_pct,
    validate_leverage,
)

_OPEN_SIDE = {"BUY": "LONG", "SELL": "SHORT"}
_REDUCE_SIDE = {"BUY": "SHORT", "SELL": "LONG"}  # the position side this side of order reduces


class OrderRejected(ValueError):
    """Raised for any order that fails validation -- the API layer turns
    this into a 400, and the order row (when one was already created) is
    persisted with status=REJECTED + reject_reason rather than silently
    dropped, so a rejected order is still visible in Order History."""


async def _existing_order(session: AsyncSession, client_order_id: str) -> FuturesSimOrder | None:
    return await session.scalar(
        select(FuturesSimOrder).where(FuturesSimOrder.client_order_id == client_order_id)
    )


async def _open_position_for_symbol(
    session: AsyncSession, account_id: int, symbol: str
) -> FuturesSimPosition | None:
    return await session.scalar(
        select(FuturesSimPosition).where(
            FuturesSimPosition.account_id == account_id,
            FuturesSimPosition.symbol == symbol,
            FuturesSimPosition.status == "OPEN",
        )
    )


async def _other_open_positions_unrealized_pnl(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    account_id: int,
    exclude_position_id: int | None,
) -> float:
    """Sum of every OTHER open position's unrealized PnL for this account --
    the cushion CROSS liquidation math adds on top of a position's own
    initial margin (task: "available account equity участвует в
    поддержании позиций"). `exclude_position_id` is None for a brand-new
    position that hasn't been flushed yet (nothing to exclude, since it
    can't appear in this query's results anyway)."""
    query = select(FuturesSimPosition).where(
        FuturesSimPosition.account_id == account_id, FuturesSimPosition.status == "OPEN"
    )
    if exclude_position_id is not None:
        query = query.where(FuturesSimPosition.id != exclude_position_id)
    other_positions = list(await session.scalars(query))
    total = 0.0
    for other in other_positions:
        price_info = await get_current_price(session_factory, redis, other.symbol)
        mark = price_info["price"] if price_info is not None else float(other.mark_price)
        total += compute_position_pnl(
            other.side, float(other.entry_price), mark, float(other.quantity)
        )
    return total


async def _recompute_liquidation_price(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    account: FuturesSimAccount,
    position: FuturesSimPosition,
    maintenance_margin_pct: float,
) -> None:
    """ISOLATED: this position's own initial margin is the only cushion.
    CROSS: the rest of the account's equity (wallet balance plus every
    OTHER open position's unrealized PnL) adds to that cushion, so a CROSS
    position generally liquidates later than the same position would in
    ISOLATED mode -- see compute_cross_liquidation_price's own docstring
    for the full derivation."""
    if position.margin_mode == "ISOLATED":
        position.liquidation_price = compute_isolated_liquidation_price(
            position.side, float(position.entry_price), position.leverage, maintenance_margin_pct
        )
    else:
        other_pnl = await _other_open_positions_unrealized_pnl(
            session, session_factory, redis, account.id, position.id
        )
        other_account_equity = float(account.wallet_balance) + other_pnl
        position.liquidation_price = compute_cross_liquidation_price(
            position.side,
            float(position.entry_price),
            float(position.quantity),
            float(position.initial_margin),
            float(position.maintenance_margin),
            other_account_equity,
        )


async def place_market_order(
    account: FuturesSimAccount,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    *,
    symbol: str,
    side: str,
    quantity: float,
    leverage: int,
    margin_mode: str = "ISOLATED",
    reduce_only: bool = False,
    client_order_id: str | None = None,
    strategy_tag: str = "manual",
    prediction_id: int | None = None,
) -> dict:
    """Places and immediately fills a simulated MARKET order (task: "Market
    order должен исполняться сразу при наличии корректного market data").
    Returns {"order": FuturesSimOrder, "position": FuturesSimPosition | None,
    "trade": FuturesSimTrade | None} -- `trade` is set only when this order
    closed/reduced a position (a realized trade), `position` is the
    resulting open position (None if this order fully closed it out)."""
    symbol = symbol.upper()
    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise OrderRejected(f"side must be BUY or SELL, got {side!r}")
    if quantity <= 0:
        raise OrderRejected("quantity must be positive")
    if margin_mode not in ("ISOLATED", "CROSS"):
        raise OrderRejected(f"margin_mode must be ISOLATED or CROSS, got {margin_mode!r}")
    validate_leverage(symbol, leverage)  # raises OrderRejected's parent ValueError on failure

    client_order_id = client_order_id or str(uuid.uuid4())

    async with session_factory() as session:
        # `account` was loaded by a different (already-closed) session --
        # mutating its wallet_balance/fees_paid_total/realized_pnl_total in
        # place and committing THIS session would silently drop those
        # writes (a detached instance not in this session's identity map
        # never gets flushed). Re-bind to this session's own copy of the
        # same row before anything below mutates it.
        account = await session.get(FuturesSimAccount, account.id)

        existing = await _existing_order(session, client_order_id)
        if existing is not None:
            position = (
                await session.get(FuturesSimPosition, existing.position_id)
                if existing.position_id is not None
                else None
            )
            return {
                "order": existing,
                "position": position,
                "trade": None,
                "idempotent_replay": True,
            }

        position = await _open_position_for_symbol(session, account.id, symbol)

        price_info = await get_current_price(session_factory, redis, symbol)
        if price_info is None:
            order = FuturesSimOrder(
                account_id=account.id,
                client_order_id=client_order_id,
                symbol=symbol,
                side=side,
                position_side=_OPEN_SIDE[side],
                order_type="MARKET",
                margin_mode=margin_mode,
                leverage=leverage,
                quantity=quantity,
                reduce_only=reduce_only,
                status="REJECTED",
                reject_reason=f"No market data available for {symbol}",
                strategy_tag=strategy_tag,
                prediction_id=prediction_id,
            )
            session.add(order)
            await session.commit()
            raise OrderRejected(order.reject_reason)

        reference_price = price_info["price"]
        fill = compute_market_fill_price(side, reference_price)
        fee_info = compute_fee(quantity * fill["actual_fill_price"], is_maker=False)

        order = FuturesSimOrder(
            account_id=account.id,
            symbol=symbol,
            side=side,
            position_side=_OPEN_SIDE[side],
            order_type="MARKET",
            margin_mode=margin_mode,
            leverage=leverage,
            quantity=quantity,
            reduce_only=reduce_only,
            client_order_id=client_order_id,
            requested_price=fill["requested_price"],
            estimated_fill_price=fill["estimated_fill_price"],
            actual_fill_price=fill["actual_fill_price"],
            slippage_pct=fill["slippage_pct"],
            fee_rate_pct=fee_info["fee_rate_pct"],
            fee_amount=fee_info["fee_amount"],
            strategy_tag=strategy_tag,
            prediction_id=prediction_id,
        )

        return await execute_fill(
            session,
            session_factory,
            redis,
            account,
            order,
            position,
            symbol=symbol,
            side=side,
            quantity=quantity,
            leverage=leverage,
            margin_mode=margin_mode,
            reduce_only=reduce_only,
            fill=fill,
            fee_info=fee_info,
        )


async def execute_fill(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    account: FuturesSimAccount,
    order: FuturesSimOrder,
    position: FuturesSimPosition | None,
    *,
    symbol: str,
    side: str,
    quantity: float,
    leverage: int,
    margin_mode: str,
    reduce_only: bool,
    fill: dict,
    fee_info: dict,
) -> dict:
    """Shared fill-execution path: everything that happens once a fill
    price has been determined, regardless of how it got there -- an
    immediate MARKET fill (place_market_order, above) or a resting LIMIT/
    STOP_MARKET/TAKE_PROFIT_MARKET order crossing its trigger price
    (app.services.futures_sim.resting_orders.check_resting_orders_for_fills).
    `order` must already exist (added to `session`, not yet committed) with
    its type-specific fields (price/stop_price/requested_price/etc.) set by
    the caller -- this function only handles the open/increase/reduce/close/
    flip branching (§5 of docs/FUTURES_SIMULATOR_MATH.md), fee accounting,
    and the final order-status update + commit."""
    trade: FuturesSimTrade | None = None
    opens_side = _OPEN_SIDE[side]
    filled_quantity = quantity

    if position is None:
        if reduce_only:
            order.status = "REJECTED"
            order.reject_reason = "reduceOnly: no open position to reduce"
            session.add(order)
            await session.commit()
            raise OrderRejected(order.reject_reason)
        position = await _open_new_position(
            session,
            session_factory,
            redis,
            account,
            symbol,
            opens_side,
            quantity,
            leverage,
            margin_mode,
            fill,
            fee_info,
        )
    elif position.side == opens_side:
        if reduce_only:
            order.status = "REJECTED"
            order.reject_reason = "reduceOnly: this order would increase exposure, not reduce it"
            session.add(order)
            await session.commit()
            raise OrderRejected(order.reject_reason)
        await _increase_position(
            session, session_factory, redis, account, position, quantity, fill, fee_info
        )
    else:
        # Fee for the close leg is computed on close_quantity, not the
        # full requested `quantity` -- when quantity exceeds the
        # position size (flip or a reduceOnly cap), charging the close
        # leg on the full requested quantity would either double-charge
        # the flip's overlap portion (once here, once on the new
        # position's own open fee) or overcharge a reduceOnly order for
        # a remainder that never actually executes.
        close_quantity = min(quantity, float(position.quantity))
        close_fee_info = compute_fee(close_quantity * fill["actual_fill_price"], is_maker=False)
        trade = await _close_or_reduce_position(
            session,
            session_factory,
            redis,
            account,
            position,
            close_quantity,
            fill,
            close_fee_info,
            exit_reason="MANUAL",
        )
        total_fee_amount = close_fee_info["fee_amount"]
        remainder = quantity - close_quantity
        if remainder > 0 and not reduce_only:
            # Flip: the closing order's excess quantity opens a brand
            # new position in the other direction, exactly like a real
            # one-way-mode exchange would net it out in a single order.
            flip_fee = compute_fee(remainder * fill["actual_fill_price"], is_maker=False)
            position = await _open_new_position(
                session,
                session_factory,
                redis,
                account,
                symbol,
                opens_side,
                remainder,
                leverage,
                margin_mode,
                fill,
                flip_fee,
            )
            total_fee_amount += flip_fee["fee_amount"]
        else:
            # reduceOnly cap (or an exact/partial close with no
            # remainder): the unexecuted remainder, if any, is simply
            # not filled -- never flipped, never charged a fee.
            filled_quantity = close_quantity
            position = await _open_position_for_symbol(session, account.id, symbol)
        order.fee_amount = total_fee_amount

    order.status = "FILLED"
    order.filled_quantity = filled_quantity
    order.filled_at = datetime.now(UTC)
    order.position_id = position.id if position is not None else None
    session.add(order)
    await session.commit()
    if position is not None:
        await session.refresh(position)
    if trade is not None:
        await session.refresh(trade)

    return {"order": order, "position": position, "trade": trade, "idempotent_replay": False}


async def _open_new_position(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    account: FuturesSimAccount,
    symbol: str,
    side: str,
    quantity: float,
    leverage: int,
    margin_mode: str,
    fill: dict,
    fee_info: dict,
) -> FuturesSimPosition:
    fill_price = fill["actual_fill_price"]
    notional = quantity * fill_price
    initial_margin = compute_initial_margin(notional, leverage)
    maintenance_margin_pct = resolve_maintenance_margin_pct(symbol)
    maintenance_margin = compute_maintenance_margin(notional, maintenance_margin_pct)

    account_state = await _current_available_margin(session, account)
    if initial_margin + fee_info["fee_amount"] > account_state:
        raise OrderRejected(
            f"Insufficient margin: need {initial_margin + fee_info['fee_amount']:.2f}, "
            f"have {account_state:.2f} available"
        )

    position = FuturesSimPosition(
        account_id=account.id,
        symbol=symbol,
        side=side,
        margin_mode=margin_mode,
        leverage=leverage,
        quantity=quantity,
        entry_price=fill_price,
        mark_price=fill_price,
        initial_margin=initial_margin,
        maintenance_margin=maintenance_margin,
        status="OPEN",
    )
    session.add(position)
    await session.flush()  # assigns position.id before the CROSS-mode exclusion query below
    await _recompute_liquidation_price(
        session, session_factory, redis, account, position, maintenance_margin_pct
    )
    await _apply_fee(session, account, fee_info["fee_amount"], reference_type="POSITION")
    session.add(
        FuturesSimLedgerEntry(
            account_id=account.id,
            event_type="OPEN",
            amount=0,
            balance_after=float(account.wallet_balance),
            reference_type="POSITION",
            reference_id=position.id,
            description=(
                f"Opened {side} {quantity} {symbol} @ {fill_price:.8f} "
                f"({leverage}x, {margin_mode})"
            ),
        )
    )
    return position


async def _increase_position(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    account: FuturesSimAccount,
    position: FuturesSimPosition,
    quantity: float,
    fill: dict,
    fee_info: dict,
) -> None:
    fill_price = fill["actual_fill_price"]
    old_quantity = float(position.quantity)
    old_entry = float(position.entry_price)
    new_quantity = old_quantity + quantity
    # Weighted-average entry price -- the standard exchange convention for
    # adding to an existing position, not a fabricated approximation.
    new_entry = (old_entry * old_quantity + fill_price * quantity) / new_quantity
    notional = new_quantity * new_entry
    initial_margin = compute_initial_margin(notional, position.leverage)
    maintenance_margin_pct = resolve_maintenance_margin_pct(position.symbol)
    maintenance_margin = compute_maintenance_margin(notional, maintenance_margin_pct)

    added_margin = initial_margin - float(position.initial_margin)
    account_state = await _current_available_margin(session, account)
    if added_margin + fee_info["fee_amount"] > account_state:
        raise OrderRejected(
            f"Insufficient margin: need {added_margin + fee_info['fee_amount']:.2f}, "
            f"have {account_state:.2f} available"
        )

    position.quantity = new_quantity
    position.entry_price = new_entry
    position.initial_margin = initial_margin
    position.maintenance_margin = maintenance_margin
    position.updated_at = datetime.now(UTC)
    await _recompute_liquidation_price(
        session, session_factory, redis, account, position, maintenance_margin_pct
    )
    await _apply_fee(session, account, fee_info["fee_amount"], reference_type="POSITION")
    session.add(
        FuturesSimLedgerEntry(
            account_id=account.id,
            event_type="OPEN",
            amount=0,
            balance_after=float(account.wallet_balance),
            reference_type="POSITION",
            reference_id=position.id,
            description=(
                f"Increased {position.side} {position.symbol} by {quantity} @ {fill_price:.8f}"
            ),
        )
    )


async def _close_or_reduce_position(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    account: FuturesSimAccount,
    position: FuturesSimPosition,
    close_quantity: float,
    fill: dict,
    fee_info: dict,
    *,
    exit_reason: str,
) -> FuturesSimTrade:
    fill_price = fill["actual_fill_price"]
    entry_price = float(position.entry_price)
    gross_pnl = compute_position_pnl(position.side, entry_price, fill_price, close_quantity)
    fee_amount = fee_info["fee_amount"]
    net_pnl = compute_net_pnl(gross_pnl, fee_amount, funding=0.0)
    margin_used = compute_initial_margin(close_quantity * entry_price, position.leverage)
    roi_pct = compute_roi_pct(net_pnl, margin_used)

    now = datetime.now(UTC)
    trade = FuturesSimTrade(
        account_id=account.id,
        position_id=position.id,
        symbol=position.symbol,
        side=position.side,
        leverage=position.leverage,
        entry_price=entry_price,
        exit_price=fill_price,
        quantity=close_quantity,
        gross_pnl=gross_pnl,
        fees=fee_amount,
        funding=0.0,
        net_pnl=net_pnl,
        roi_pct=roi_pct if roi_pct is not None else 0.0,
        opened_at=position.opened_at,
        closed_at=now,
        duration_seconds=max(0, int((now - position.opened_at).total_seconds())),
        exit_reason=exit_reason,
        strategy_tag="manual",
    )
    session.add(trade)

    remaining_quantity = float(position.quantity) - close_quantity
    account.wallet_balance = float(account.wallet_balance) + net_pnl
    account.realized_pnl_total = float(account.realized_pnl_total) + net_pnl
    account.fees_paid_total = float(account.fees_paid_total) + fee_amount

    if remaining_quantity <= 1e-12:
        position.status = "CLOSED"
        position.close_reason = exit_reason
        position.closed_at = now
        position.quantity = 0
    else:
        position.quantity = remaining_quantity
        position.realized_pnl = float(position.realized_pnl) + net_pnl
        notional = remaining_quantity * entry_price
        maintenance_margin_pct = resolve_maintenance_margin_pct(position.symbol)
        position.initial_margin = compute_initial_margin(notional, position.leverage)
        position.maintenance_margin = compute_maintenance_margin(notional, maintenance_margin_pct)
        await _recompute_liquidation_price(
            session, session_factory, redis, account, position, maintenance_margin_pct
        )
    position.updated_at = now

    session.add(
        FuturesSimLedgerEntry(
            account_id=account.id,
            event_type="REALIZED_PNL",
            amount=net_pnl,
            balance_after=float(account.wallet_balance),
            reference_type="TRADE",
            reference_id=None,
            description=(
                f"Closed {close_quantity} {position.symbol} {position.side} @ {fill_price:.8f} "
                f"({exit_reason}), net PnL {net_pnl:+.2f}"
            ),
        )
    )
    await session.flush()
    trade.position_id = position.id
    session.add(
        FuturesSimLedgerEntry(
            account_id=account.id,
            event_type="FEE",
            amount=-fee_amount,
            balance_after=float(account.wallet_balance),
            reference_type="TRADE",
            reference_id=trade.id,
            description=f"Taker fee for closing {position.symbol}",
        )
    )
    return trade


async def _apply_fee(
    session: AsyncSession, account: FuturesSimAccount, fee_amount: float, *, reference_type: str
) -> None:
    account.wallet_balance = float(account.wallet_balance) - fee_amount
    account.fees_paid_total = float(account.fees_paid_total) + fee_amount
    session.add(
        FuturesSimLedgerEntry(
            account_id=account.id,
            event_type="FEE",
            amount=-fee_amount,
            balance_after=float(account.wallet_balance),
            reference_type=reference_type,
            reference_id=None,
            description="Taker fee",
        )
    )


async def _current_available_margin(session: AsyncSession, account: FuturesSimAccount) -> float:
    """Available margin BEFORE this order's own effect -- sums every other
    OPEN position's initial margin against the account's current wallet
    balance. Deliberately does not call FuturesSimEngine.get_account_state
    (which also fetches live mark prices for unrealized PnL) to avoid an
    extra round of price lookups mid-transaction; margin *availability*
    checks only need used_margin, not unrealized PnL, to stay conservative
    and simple for this increment."""
    positions = list(
        await session.scalars(
            select(FuturesSimPosition).where(
                FuturesSimPosition.account_id == account.id, FuturesSimPosition.status == "OPEN"
            )
        )
    )
    used_margin = sum(float(p.initial_margin) for p in positions)
    return float(account.wallet_balance) - used_margin


async def close_position(
    account: FuturesSimAccount,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    *,
    position_id: int,
    quantity: float | None = None,
    exit_reason: str = "MANUAL",
) -> FuturesSimTrade:
    """Task: "Close / Close 25% / Close 50% / Close 75% / Close 100%" --
    `quantity=None` means full close. Also the primitive
    app.services.futures_sim.monitor.check_positions_for_triggers uses for
    SL/TP/liquidation auto-closes (`exit_reason` is how those differ from
    a manual close)."""
    async with session_factory() as session:
        # See the matching comment in place_market_order: `account` may
        # have been loaded by a different, already-closed session -- rebind
        # to this session's own copy before anything below mutates it.
        account = await session.get(FuturesSimAccount, account.id)
        position = await session.get(FuturesSimPosition, position_id)
        if position is None or position.status != "OPEN" or position.account_id != account.id:
            raise OrderRejected(f"No open position {position_id} on this account")

        close_quantity = float(position.quantity) if quantity is None else quantity
        if close_quantity <= 0 or close_quantity > float(position.quantity) + 1e-12:
            raise OrderRejected(
                f"quantity must be between 0 and the open position size ({position.quantity})"
            )

        price_info = await get_current_price(session_factory, redis, position.symbol)
        if price_info is None:
            raise OrderRejected(f"No market data available for {position.symbol}")

        closing_side = "SELL" if position.side == "LONG" else "BUY"
        fill = compute_market_fill_price(closing_side, price_info["price"])
        fee_info = compute_fee(close_quantity * fill["actual_fill_price"], is_maker=False)

        trade = await _close_or_reduce_position(
            session,
            session_factory,
            redis,
            account,
            position,
            close_quantity,
            fill,
            fee_info,
            exit_reason=exit_reason,
        )
        await session.commit()
        await session.refresh(trade)
        return trade


async def set_stop_loss_take_profit(
    account: FuturesSimAccount,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    position_id: int,
    sl_price: float | None,
    tp_price: float | None,
) -> FuturesSimPosition:
    """Task: position-level Stop Loss / Take Profit. Sets (or clears, by
    passing None) the trigger prices on an OPEN position -- these are
    plain price triggers checked on every
    app.services.futures_sim.monitor.check_positions_for_triggers pass,
    not real conditional orders placed on any exchange. Validated against
    the position's own side and entry price so a SL/TP can never be set on
    the wrong side of entry (a LONG's stop-loss must sit below entry and
    its take-profit above; SHORT is the mirror image) -- an inverted
    SL/TP would either never trigger or trigger immediately, neither of
    which is what "stop loss" or "take profit" means."""
    async with session_factory() as session:
        account = await session.get(FuturesSimAccount, account.id)
        position = await session.get(FuturesSimPosition, position_id)
        if position is None or position.status != "OPEN" or position.account_id != account.id:
            raise OrderRejected(f"No open position {position_id} on this account")

        entry_price = float(position.entry_price)
        if sl_price is not None:
            if position.side == "LONG" and sl_price >= entry_price:
                raise OrderRejected("stop-loss for a LONG position must be below entry price")
            if position.side == "SHORT" and sl_price <= entry_price:
                raise OrderRejected("stop-loss for a SHORT position must be above entry price")
        if tp_price is not None:
            if position.side == "LONG" and tp_price <= entry_price:
                raise OrderRejected("take-profit for a LONG position must be above entry price")
            if position.side == "SHORT" and tp_price >= entry_price:
                raise OrderRejected("take-profit for a SHORT position must be below entry price")

        position.sl_price = sl_price
        position.tp_price = tp_price
        position.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(position)
        return position


async def place_limit_order(
    account: FuturesSimAccount,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    *,
    symbol: str,
    side: str,
    quantity: float,
    leverage: int,
    price: float,
    margin_mode: str = "ISOLATED",
    reduce_only: bool = False,
    client_order_id: str | None = None,
    strategy_tag: str = "manual",
    prediction_id: int | None = None,
) -> dict:
    """Places a resting LIMIT order (status=NEW) -- does NOT fill
    immediately. app.services.futures_sim.resting_orders.
    check_resting_orders_for_fills fills it, at exactly `price` (never
    with slippage -- the entire point of a limit order is a guaranteed
    price), once the current mark price crosses `price` favorably: a BUY
    fills once price <= `price`, a SELL fills once price >= `price`.

    Deterministic fill model (task's own stated preference over an
    unrealistic partial-fill simulation): this simulator has no order
    book, so a resting order either fills completely or stays NEW --
    never PARTIALLY_FILLED.

    Margin sufficiency is NOT checked at placement time (this simulator
    does not reserve margin for resting orders); it is re-checked at fill
    time and the order is REJECTED then if margin has become insufficient
    in the meantime -- a documented simplification versus a real
    exchange's margin-reservation model."""
    symbol = symbol.upper()
    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise OrderRejected(f"side must be BUY or SELL, got {side!r}")
    if quantity <= 0:
        raise OrderRejected("quantity must be positive")
    if price <= 0:
        raise OrderRejected("price must be positive")
    if margin_mode not in ("ISOLATED", "CROSS"):
        raise OrderRejected(f"margin_mode must be ISOLATED or CROSS, got {margin_mode!r}")
    validate_leverage(symbol, leverage)

    client_order_id = client_order_id or str(uuid.uuid4())
    async with session_factory() as session:
        existing = await _existing_order(session, client_order_id)
        if existing is not None:
            return {"order": existing, "idempotent_replay": True}

        order = FuturesSimOrder(
            account_id=account.id,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            position_side=_OPEN_SIDE[side],
            order_type="LIMIT",
            margin_mode=margin_mode,
            leverage=leverage,
            quantity=quantity,
            price=price,
            reduce_only=reduce_only,
            status="NEW",
            strategy_tag=strategy_tag,
            prediction_id=prediction_id,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return {"order": order, "idempotent_replay": False}


async def place_stop_order(
    account: FuturesSimAccount,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    *,
    symbol: str,
    side: str,
    quantity: float,
    leverage: int,
    stop_price: float,
    order_type: str,
    margin_mode: str = "ISOLATED",
    reduce_only: bool = False,
    client_order_id: str | None = None,
    strategy_tag: str = "manual",
    prediction_id: int | None = None,
) -> dict:
    """Places a resting STOP_MARKET or TAKE_PROFIT_MARKET order
    (status=NEW). Both order types trigger identically -- the type only
    labels intent (a protective stop vs. a target), not different trigger
    mechanics, matching real exchange semantics: a BUY triggers once price
    rises to or above `stop_price`, a SELL triggers once price falls to or
    below it. Once triggered, the order fills as a MARKET order (with
    slippage, since it is genuinely a market order from that point on) --
    see app.services.futures_sim.resting_orders.check_resting_orders_for_fills."""
    if order_type not in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
        raise OrderRejected(
            f"order_type must be STOP_MARKET or TAKE_PROFIT_MARKET, got {order_type!r}"
        )
    symbol = symbol.upper()
    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise OrderRejected(f"side must be BUY or SELL, got {side!r}")
    if quantity <= 0:
        raise OrderRejected("quantity must be positive")
    if stop_price <= 0:
        raise OrderRejected("stop_price must be positive")
    if margin_mode not in ("ISOLATED", "CROSS"):
        raise OrderRejected(f"margin_mode must be ISOLATED or CROSS, got {margin_mode!r}")
    validate_leverage(symbol, leverage)

    client_order_id = client_order_id or str(uuid.uuid4())
    async with session_factory() as session:
        existing = await _existing_order(session, client_order_id)
        if existing is not None:
            return {"order": existing, "idempotent_replay": True}

        order = FuturesSimOrder(
            account_id=account.id,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            position_side=_OPEN_SIDE[side],
            order_type=order_type,
            margin_mode=margin_mode,
            leverage=leverage,
            quantity=quantity,
            stop_price=stop_price,
            reduce_only=reduce_only,
            status="NEW",
            strategy_tag=strategy_tag,
            prediction_id=prediction_id,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return {"order": order, "idempotent_replay": False}


async def cancel_order(
    account: FuturesSimAccount,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    order_id: int,
) -> FuturesSimOrder:
    """Cancels a resting (status=NEW) LIMIT/STOP_MARKET/TAKE_PROFIT_MARKET
    order. MARKET orders are never cancellable -- they fill synchronously
    inside place_market_order and never reach a resting state."""
    async with session_factory() as session:
        order = await session.get(FuturesSimOrder, order_id)
        if order is None or order.account_id != account.id:
            raise OrderRejected(f"No order {order_id} on this account")
        if order.status != "NEW":
            raise OrderRejected(f"Order {order_id} is {order.status}, not cancellable")

        order.status = "CANCELLED"
        order.cancelled_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(order)
        return order
