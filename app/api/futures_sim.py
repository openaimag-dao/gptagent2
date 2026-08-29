"""Futures Simulator API -- 100% demo/paper trading, no real money, no real
exchange orders. Most mutating endpoints are gated by require_admin_key, the
same single-shared-key mechanism app/api/portfolio.py and app/api/admin.py
already use (this project has no user/auth model at all -- see
FuturesSimAccount's own docstring). Opening (`POST /orders`) and closing
(`POST /positions/{id}/close`) a position are deliberately ungated -- task:
no password prompt on the two core demo-trading actions, only fake money is
ever at stake either way. Every other mutating action (account reset,
cancelling a resting order, setting SL/TP, journal notes, risk-settings
overrides) keeps the admin-key gate. Read endpoints stay open, matching how
every other read endpoint in this app already behaves."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.admin import require_admin_key
from app.config import get_settings
from app.database.models import (
    FuturesSimAccount,
    FuturesSimLedgerEntry,
    FuturesSimOrder,
    FuturesSimPosition,
    FuturesSimTrade,
)
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.futures_sim.engine import (
    DEFAULT_ACCOUNT_NAME,
    available_leverage_options,
    build_futures_sim_engine,
    compute_position_pnl,
    compute_roi_pct,
    get_mark_price,
    resolve_leverage_bracket,
)
from app.services.futures_sim.journal import (
    SELF_ASSESSMENT_TAGS,
    STRATEGY_LABELS,
    InvalidJournalEntry,
    validate_journal_update,
)
from app.services.futures_sim.orders import (
    OrderRejected,
    cancel_order,
    close_position,
    place_limit_order,
    place_market_order,
    place_stop_order,
    set_stop_loss_take_profit,
)
from app.services.futures_sim.performance import compute_performance_stats
from app.services.futures_sim.risk import compute_risk_metrics
from app.services.realtime.config import parse_watchlist

router = APIRouter(prefix="/api/simulator", tags=["futures-simulator"])


class PlaceOrderRequest(BaseModel):
    symbol: str
    side: str  # BUY / SELL
    order_type: str = "MARKET"  # MARKET / LIMIT / STOP_MARKET / TAKE_PROFIT_MARKET
    quantity: float
    leverage: int = 1
    margin_mode: str = "ISOLATED"
    price: float | None = None  # required for LIMIT
    stop_price: float | None = None  # required for STOP_MARKET / TAKE_PROFIT_MARKET
    reduce_only: bool = False
    client_order_id: str | None = None
    strategy_tag: str = "manual"
    prediction_id: int | None = None
    account_name: str = DEFAULT_ACCOUNT_NAME


class ClosePositionRequest(BaseModel):
    quantity: float | None = None
    percent: float | None = None  # 0-100, alternative to quantity (task: 25/50/75/100%)
    account_name: str = DEFAULT_ACCOUNT_NAME


class SetStopLossTakeProfitRequest(BaseModel):
    sl_price: float | None = None
    tp_price: float | None = None  # either field omitted/None clears that trigger
    account_name: str = DEFAULT_ACCOUNT_NAME


class UpdateRiskSettingsRequest(BaseModel):
    # Task: Max Risk Settings (optional, per-account). Each field is a
    # full-replace override: a value sets it, None (the default, or an
    # explicit null) reverts that one threshold back to the global
    # futures_sim_risk_* setting. Never blocks trading -- only changes
    # when a Risk Metrics warning fires.
    high_margin_ratio_pct: float | None = Field(default=None, gt=0)
    near_liquidation_pct: float | None = Field(default=None, gt=0)
    margin_warning_available_pct: float | None = Field(default=None, gt=0)
    daily_loss_warning_pct: float | None = Field(default=None, gt=0)
    account_name: str = DEFAULT_ACCOUNT_NAME


class UpdateTradeJournalRequest(BaseModel):
    # None means "leave this field unchanged" -- self_assessment_tags=[]
    # (an empty list, not None) is how a caller clears the tag list.
    strategy_label: str | None = None
    note: str | None = None
    self_assessment_tags: list[str] | None = None
    account_name: str = DEFAULT_ACCOUNT_NAME


def _serialize_account_state(state: dict) -> dict:
    return {
        **{k: v for k, v in state.items() if k not in ("created_at", "reset_at")},
        "created_at": state["created_at"].isoformat(),
        "reset_at": state["reset_at"].isoformat() if state["reset_at"] is not None else None,
        "paper_trading": True,
        "real_funds_used": False,
    }


def _serialize_position(position: FuturesSimPosition) -> dict:
    return {
        "position_id": position.id,
        "account_id": position.account_id,
        "symbol": position.symbol,
        "side": position.side,
        "margin_mode": position.margin_mode,
        "leverage": position.leverage,
        "quantity": float(position.quantity),
        "entry_price": float(position.entry_price),
        "mark_price": float(position.mark_price),
        "initial_margin": float(position.initial_margin),
        "maintenance_margin": float(position.maintenance_margin),
        "realized_pnl": float(position.realized_pnl),
        "funding_paid": float(position.funding_paid),
        "liquidation_price": float(position.liquidation_price)
        if position.liquidation_price is not None
        else None,
        "sl_price": float(position.sl_price) if position.sl_price is not None else None,
        "tp_price": float(position.tp_price) if position.tp_price is not None else None,
        "status": position.status,
        "close_reason": position.close_reason,
        "opened_at": position.opened_at.isoformat(),
        "updated_at": position.updated_at.isoformat(),
        "closed_at": position.closed_at.isoformat() if position.closed_at is not None else None,
    }


def _serialize_order(order: FuturesSimOrder) -> dict:
    return {
        "order_id": order.id,
        "client_order_id": order.client_order_id,
        "position_id": order.position_id,
        "symbol": order.symbol,
        "side": order.side,
        "position_side": order.position_side,
        "order_type": order.order_type,
        "margin_mode": order.margin_mode,
        "leverage": order.leverage,
        "quantity": float(order.quantity),
        "price": float(order.price) if order.price is not None else None,
        "stop_price": float(order.stop_price) if order.stop_price is not None else None,
        "reduce_only": order.reduce_only,
        "status": order.status,
        "requested_price": float(order.requested_price)
        if order.requested_price is not None
        else None,
        "estimated_fill_price": float(order.estimated_fill_price)
        if order.estimated_fill_price is not None
        else None,
        "actual_fill_price": float(order.actual_fill_price)
        if order.actual_fill_price is not None
        else None,
        "slippage_pct": float(order.slippage_pct) if order.slippage_pct is not None else None,
        "filled_quantity": float(order.filled_quantity),
        "fee_rate_pct": float(order.fee_rate_pct) if order.fee_rate_pct is not None else None,
        "fee_amount": float(order.fee_amount) if order.fee_amount is not None else None,
        "reject_reason": order.reject_reason,
        "strategy_tag": order.strategy_tag,
        "prediction_id": order.prediction_id,
        "created_at": order.created_at.isoformat(),
        "filled_at": order.filled_at.isoformat() if order.filled_at is not None else None,
        "cancelled_at": order.cancelled_at.isoformat() if order.cancelled_at is not None else None,
    }


def _serialize_trade(trade: FuturesSimTrade) -> dict:
    return {
        "trade_id": trade.id,
        "position_id": trade.position_id,
        "symbol": trade.symbol,
        "side": trade.side,
        "leverage": trade.leverage,
        "entry_price": float(trade.entry_price),
        "exit_price": float(trade.exit_price),
        "quantity": float(trade.quantity),
        "gross_pnl": float(trade.gross_pnl),
        "fees": float(trade.fees),
        "funding": float(trade.funding),
        "net_pnl": float(trade.net_pnl),
        "roi_pct": float(trade.roi_pct),
        "opened_at": trade.opened_at.isoformat(),
        "closed_at": trade.closed_at.isoformat(),
        "duration_seconds": trade.duration_seconds,
        "exit_reason": trade.exit_reason,
        "strategy_tag": trade.strategy_tag,
        "prediction_id": trade.prediction_id,
        "strategy_label": trade.strategy_label,
        "note": trade.note,
        "self_assessment_tags": trade.self_assessment_tags,
    }


def _account_risk_overrides(account: FuturesSimAccount) -> dict:
    """Task: Max Risk Settings -- this account's own override for each
    Risk Metrics warning threshold, or None where it hasn't set one (and
    app.services.futures_sim.risk.compute_risk_metrics falls back to the
    global futures_sim_risk_* setting)."""
    return {
        "high_margin_ratio_pct": float(account.risk_high_margin_ratio_pct)
        if account.risk_high_margin_ratio_pct is not None
        else None,
        "near_liquidation_pct": float(account.risk_near_liquidation_pct)
        if account.risk_near_liquidation_pct is not None
        else None,
        "margin_warning_available_pct": float(account.risk_margin_warning_available_pct)
        if account.risk_margin_warning_available_pct is not None
        else None,
        "daily_loss_warning_pct": float(account.risk_daily_loss_warning_pct)
        if account.risk_daily_loss_warning_pct is not None
        else None,
    }


@router.get("/account")
async def get_account(name: str = DEFAULT_ACCOUNT_NAME) -> dict:
    engine = build_futures_sim_engine()
    account = await engine.get_or_create_account(name)
    state = await engine.get_account_state(account)
    return _serialize_account_state(state)


@router.post("/account/reset", dependencies=[Depends(require_admin_key)])
async def reset_account(name: str = DEFAULT_ACCOUNT_NAME) -> dict:
    engine = build_futures_sim_engine()
    account = await engine.reset_account(name)
    state = await engine.get_account_state(account)
    return _serialize_account_state(state)


@router.post("/orders")
async def place_order(request: PlaceOrderRequest) -> dict:
    engine = build_futures_sim_engine()
    account = await engine.get_or_create_account(request.account_name)
    try:
        if request.order_type == "MARKET":
            result = await place_market_order(
                account,
                get_session_factory(),
                get_redis(),
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                leverage=request.leverage,
                margin_mode=request.margin_mode,
                reduce_only=request.reduce_only,
                client_order_id=request.client_order_id,
                strategy_tag=request.strategy_tag,
                prediction_id=request.prediction_id,
            )
        elif request.order_type == "LIMIT":
            if request.price is None:
                raise HTTPException(status_code=400, detail="price is required for LIMIT orders")
            result = await place_limit_order(
                account,
                get_session_factory(),
                get_redis(),
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                leverage=request.leverage,
                price=request.price,
                margin_mode=request.margin_mode,
                reduce_only=request.reduce_only,
                client_order_id=request.client_order_id,
                strategy_tag=request.strategy_tag,
                prediction_id=request.prediction_id,
            )
            result = {**result, "position": None, "trade": None}
        elif request.order_type in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
            if request.stop_price is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"stop_price is required for {request.order_type} orders",
                )
            result = await place_stop_order(
                account,
                get_session_factory(),
                get_redis(),
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                leverage=request.leverage,
                stop_price=request.stop_price,
                order_type=request.order_type,
                margin_mode=request.margin_mode,
                reduce_only=request.reduce_only,
                client_order_id=request.client_order_id,
                strategy_tag=request.strategy_tag,
                prediction_id=request.prediction_id,
            )
            result = {**result, "position": None, "trade": None}
        else:
            raise HTTPException(
                status_code=400, detail=f"Unsupported order_type {request.order_type!r}"
            )
    except OrderRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "order": _serialize_order(result["order"]),
        "position": _serialize_position(result["position"])
        if result["position"] is not None
        else None,
        "trade": _serialize_trade(result["trade"]) if result["trade"] is not None else None,
        "idempotent_replay": result["idempotent_replay"],
    }


@router.delete("/orders/{order_id}", dependencies=[Depends(require_admin_key)])
async def cancel_order_endpoint(order_id: int, account_name: str = DEFAULT_ACCOUNT_NAME) -> dict:
    """Cancels a resting (status=NEW) LIMIT/STOP_MARKET/TAKE_PROFIT_MARKET
    order. MARKET orders fill synchronously inside POST /orders and are
    never left cancellable -- attempting to cancel one (or an
    already-FILLED/CANCELLED/REJECTED order) is an honest 400 via
    OrderRejected, never a silent no-op."""
    engine = build_futures_sim_engine()
    account = await engine.get_or_create_account(account_name)
    try:
        order = await cancel_order(account, get_session_factory(), order_id=order_id)
    except OrderRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"order": _serialize_order(order)}


@router.get("/orders")
async def get_orders(
    name: str = DEFAULT_ACCOUNT_NAME, limit: int = Query(50, le=200), symbol: str | None = None
) -> dict:
    engine = build_futures_sim_engine()
    account = await engine.get_or_create_account(name)
    async with get_session_factory()() as session:
        query = select(FuturesSimOrder).where(FuturesSimOrder.account_id == account.id)
        if symbol is not None:
            query = query.where(FuturesSimOrder.symbol == symbol.upper())
        query = query.order_by(FuturesSimOrder.created_at.desc()).limit(limit)
        orders = list(await session.scalars(query))
    return {"orders": [_serialize_order(o) for o in orders]}


@router.get("/positions")
async def get_positions(name: str = DEFAULT_ACCOUNT_NAME, status: str = "OPEN") -> dict:
    engine = build_futures_sim_engine()
    account = await engine.get_or_create_account(name)
    async with get_session_factory()() as session:
        query = select(FuturesSimPosition).where(FuturesSimPosition.account_id == account.id)
        if status != "ALL":
            query = query.where(FuturesSimPosition.status == status)
        query = query.order_by(FuturesSimPosition.opened_at.desc())
        positions = list(await session.scalars(query))

    serialized = []
    for position in positions:
        payload = _serialize_position(position)
        if position.status == "OPEN":
            # SIMULATED MARK PRICE (task: never just the last traded
            # price) -- see engine.get_mark_price's own docstring.
            price_info = await get_mark_price(get_session_factory(), get_redis(), position.symbol)
            mark_price = (
                price_info["price"] if price_info is not None else float(position.mark_price)
            )
            pnl = compute_position_pnl(
                position.side, float(position.entry_price), mark_price, float(position.quantity)
            )
            payload["mark_price"] = mark_price
            payload["mark_price_simulated"] = True
            payload["unrealized_pnl"] = pnl
            payload["roi_pct"] = compute_roi_pct(pnl, float(position.initial_margin))
        serialized.append(payload)
    return {"positions": serialized}


@router.post("/positions/{position_id}/close")
async def close_position_endpoint(position_id: int, request: ClosePositionRequest) -> dict:
    engine = build_futures_sim_engine()
    account = await engine.get_or_create_account(request.account_name)

    quantity = request.quantity
    if quantity is None and request.percent is not None:
        if not (0 < request.percent <= 100):
            raise HTTPException(status_code=400, detail="percent must be between 0 and 100")
        async with get_session_factory()() as session:
            position = await session.get(FuturesSimPosition, position_id)
        if position is None:
            raise HTTPException(status_code=404, detail=f"No position {position_id}")
        quantity = float(position.quantity) * request.percent / 100

    try:
        trade = await close_position(
            account,
            get_session_factory(),
            get_redis(),
            position_id=position_id,
            quantity=quantity,
        )
    except OrderRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"trade": _serialize_trade(trade)}


@router.post("/positions/{position_id}/sl-tp", dependencies=[Depends(require_admin_key)])
async def set_position_sl_tp(position_id: int, request: SetStopLossTakeProfitRequest) -> dict:
    """Task: position-level Stop Loss / Take Profit. Never triggered by
    the AI forecast automatically -- the user sets these explicitly (or
    clears one by omitting it), and they're checked on every scheduled
    app.services.futures_sim.monitor.check_positions_for_triggers pass."""
    engine = build_futures_sim_engine()
    account = await engine.get_or_create_account(request.account_name)
    try:
        position = await set_stop_loss_take_profit(
            account,
            get_session_factory(),
            position_id=position_id,
            sl_price=request.sl_price,
            tp_price=request.tp_price,
        )
    except OrderRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"position": _serialize_position(position)}


@router.get("/trades")
async def get_trades(
    name: str = DEFAULT_ACCOUNT_NAME, limit: int = Query(50, le=200), symbol: str | None = None
) -> dict:
    engine = build_futures_sim_engine()
    account = await engine.get_or_create_account(name)
    async with get_session_factory()() as session:
        query = select(FuturesSimTrade).where(FuturesSimTrade.account_id == account.id)
        if symbol is not None:
            query = query.where(FuturesSimTrade.symbol == symbol.upper())
        query = query.order_by(FuturesSimTrade.closed_at.desc()).limit(limit)
        trades = list(await session.scalars(query))
    return {"trades": [_serialize_trade(t) for t in trades]}


@router.get("/journal-options")
async def get_journal_options() -> dict:
    """Task: Strategy Journal / Trade Review -- the canonical
    strategy_label and self_assessment_tags values, so the dashboard never
    hardcodes a second copy of the list that could drift out of sync with
    the API's own validation (app.services.futures_sim.journal)."""
    return {"strategy_labels": STRATEGY_LABELS, "self_assessment_tags": SELF_ASSESSMENT_TAGS}


@router.post("/trades/{trade_id}/journal", dependencies=[Depends(require_admin_key)])
async def update_trade_journal(trade_id: int, request: UpdateTradeJournalRequest) -> dict:
    """Task: Strategy Journal / Trade Review (optional, per-trade). Purely
    a note-taking layer over a trade that already closed -- never touches
    PnL, fees, or any financial field on the trade."""
    try:
        validate_journal_update(request.strategy_label, request.self_assessment_tags)
    except InvalidJournalEntry as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    engine = build_futures_sim_engine()
    account = await engine.get_or_create_account(request.account_name)
    async with get_session_factory()() as session:
        trade = await session.get(FuturesSimTrade, trade_id)
        if trade is None or trade.account_id != account.id:
            raise HTTPException(
                status_code=404,
                detail=f"No trade {trade_id} on account {request.account_name!r}",
            )
        if request.strategy_label is not None:
            trade.strategy_label = request.strategy_label
        if request.note is not None:
            trade.note = request.note
        if request.self_assessment_tags is not None:
            trade.self_assessment_tags = request.self_assessment_tags
        await session.commit()
        await session.refresh(trade)
        return {"trade": _serialize_trade(trade)}


@router.get("/performance")
async def get_performance(name: str = DEFAULT_ACCOUNT_NAME) -> dict:
    """Task: Performance Analytics -- overall stats plus breakdowns by
    Long/Short, symbol, leverage, and strategy tag, over every closed
    trade on this account. Reuses app.services.backtest.metrics (task's
    own anti-duplication mandate) rather than a new metrics engine."""
    engine = build_futures_sim_engine()
    account = await engine.get_or_create_account(name)
    async with get_session_factory()() as session:
        query = select(FuturesSimTrade).where(FuturesSimTrade.account_id == account.id)
        trades = list(await session.scalars(query))
    return compute_performance_stats(trades)


@router.get("/risk")
async def get_risk(name: str = DEFAULT_ACCOUNT_NAME) -> dict:
    """Task: Risk Metrics -- margin ratio, distance to liquidation,
    position concentration, account drawdown, daily loss, largest
    position/exposure, with HIGH RISK/NEAR LIQUIDATION/MARGIN WARNING
    labels. Permissive by default (never blocks anything) -- see
    app.services.futures_sim.risk's own module docstring."""
    engine = build_futures_sim_engine()
    account = await engine.get_or_create_account(name)
    account_state = await engine.get_account_state(account)

    async with get_session_factory()() as session:
        open_positions = list(
            await session.scalars(
                select(FuturesSimPosition).where(
                    FuturesSimPosition.account_id == account.id,
                    FuturesSimPosition.status == "OPEN",
                )
            )
        )
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        todays_trades = list(
            await session.scalars(
                select(FuturesSimTrade).where(
                    FuturesSimTrade.account_id == account.id,
                    FuturesSimTrade.closed_at >= today_start,
                )
            )
        )
    todays_realized_pnl = sum(float(t.net_pnl) for t in todays_trades)

    positions = []
    for position in open_positions:
        price_info = await get_mark_price(get_session_factory(), get_redis(), position.symbol)
        mark_price = price_info["price"] if price_info is not None else float(position.mark_price)
        positions.append(
            {
                "position_id": position.id,
                "symbol": position.symbol,
                "side": position.side,
                "quantity": float(position.quantity),
                "mark_price": mark_price,
                "liquidation_price": float(position.liquidation_price)
                if position.liquidation_price is not None
                else None,
            }
        )

    return compute_risk_metrics(
        account_state, positions, todays_realized_pnl, _account_risk_overrides(account)
    )


@router.get("/risk-settings")
async def get_risk_settings(name: str = DEFAULT_ACCOUNT_NAME) -> dict:
    """Task: Max Risk Settings -- this account's overrides alongside the
    global defaults, so the dashboard can show which thresholds are
    customized and what they'd fall back to."""
    engine = build_futures_sim_engine()
    account = await engine.get_or_create_account(name)
    settings = get_settings()
    return {
        "overrides": _account_risk_overrides(account),
        "defaults": {
            "high_margin_ratio_pct": settings.futures_sim_risk_high_margin_ratio_pct,
            "near_liquidation_pct": settings.futures_sim_risk_near_liquidation_pct,
            "margin_warning_available_pct": settings.futures_sim_risk_margin_warning_available_pct,
            "daily_loss_warning_pct": settings.futures_sim_risk_daily_loss_warning_pct,
        },
    }


@router.post("/risk-settings", dependencies=[Depends(require_admin_key)])
async def update_risk_settings(request: UpdateRiskSettingsRequest) -> dict:
    """Task: Max Risk Settings (optional, per-account). Full-replace: each
    field either sets that account's override or (None) reverts it to the
    global default. Never blocks trading -- same permissive-by-default
    philosophy as the rest of Risk Metrics, this only changes when a
    warning fires."""
    engine = build_futures_sim_engine()
    account = await engine.get_or_create_account(request.account_name)
    async with get_session_factory()() as session:
        account = await session.get(FuturesSimAccount, account.id)
        account.risk_high_margin_ratio_pct = request.high_margin_ratio_pct
        account.risk_near_liquidation_pct = request.near_liquidation_pct
        account.risk_margin_warning_available_pct = request.margin_warning_available_pct
        account.risk_daily_loss_warning_pct = request.daily_loss_warning_pct
        await session.commit()
        await session.refresh(account)
        overrides = _account_risk_overrides(account)
    return {"overrides": overrides}


@router.get("/ledger")
async def get_ledger(name: str = DEFAULT_ACCOUNT_NAME, limit: int = Query(100, le=500)) -> dict:
    engine = build_futures_sim_engine()
    account = await engine.get_or_create_account(name)
    async with get_session_factory()() as session:
        query = (
            select(FuturesSimLedgerEntry)
            .where(FuturesSimLedgerEntry.account_id == account.id)
            .order_by(FuturesSimLedgerEntry.created_at.desc())
            .limit(limit)
        )
        entries = list(await session.scalars(query))
    return {
        "ledger": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "amount": float(e.amount),
                "balance_after": float(e.balance_after),
                "reference_type": e.reference_type,
                "reference_id": e.reference_id,
                "description": e.description,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ]
    }


@router.get("/symbols")
async def get_symbols() -> dict:
    """Task requirement (Phase 4/5): the simulator's supported-asset
    roster plus each symbol's own SIMULATED leverage bracket -- reuses
    the existing app.services.history.registry symbol universe, not a
    separate hardcoded list (only filtered to futures_sim_symbols, since
    that registry also carries non-crypto/macro symbols this simulator
    doesn't trade)."""
    symbols = parse_watchlist(get_settings().futures_sim_symbols)
    return {
        "symbols": [
            {
                "symbol": symbol,
                "leverage_options": available_leverage_options(symbol),
                **resolve_leverage_bracket(symbol),
                "bracket_is_simulated": True,
            }
            for symbol in symbols
        ]
    }
