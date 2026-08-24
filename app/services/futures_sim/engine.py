"""Futures Simulator -- a 100% demo/paper-trading futures terminal. No real
money, no real exchange orders, no withdrawals, no live trading, no Binance
API keys anywhere in this module or this codebase. Real market data (price/
candles, via the existing app.services.history/app.services.realtime
infrastructure) drives execution; only account/position/order/fee/funding/
liquidation state is simulated and stored in the futures_sim_* tables (see
app/database/models.py).

This module holds the pure math (leverage/margin/PnL/liquidation/fees --
zero I/O, fully unit-testable) plus the account-lifecycle service functions
(get-or-create, reset, live state). Order execution (open/close/fill) lives
in app.services.futures_sim.orders, kept separate so this file stays a
single, auditable source of truth for "how is a number computed" without
also carrying "when does a fill happen."

See docs/FUTURES_SIMULATOR.md (overview) and
docs/FUTURES_SIMULATOR_MATH.md (every formula, with derivations) for the
full model this module implements.
"""

import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import FuturesSimAccount, FuturesSimLedgerEntry, FuturesSimPosition
from app.services.history.registry import find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.realtime.freshness import age_seconds, classify_freshness
from app.services.realtime.store import get_latest_ticks

DEFAULT_ACCOUNT_NAME = "default"

LEVERAGE_OPTIONS: tuple[int, ...] = (1, 2, 3, 5, 10, 15, 20, 25, 30, 50, 75)

# SIMULATED leverage/maintenance-margin brackets -- NOT real Binance limits,
# never presented as such (task requirement). One flat tier per symbol
# (max_leverage, maintenance_margin_pct), roughly ordered by real-world
# liquidity/volatility so training "feels" realistic (deep, liquid majors
# get more leverage headroom, smaller caps get less) without claiming to be
# sourced from any real exchange's tiered notional brackets. Configurable:
# edit this table (or, later, move it to a DB-backed settings surface) --
# there is no live-fetched "real" bracket to keep in sync with.
FUTURES_LEVERAGE_BRACKETS: dict[str, dict] = {
    "BTC": {"max_leverage": 75, "maintenance_margin_pct": 0.4},
    "ETH": {"max_leverage": 75, "maintenance_margin_pct": 0.5},
    "SOL": {"max_leverage": 50, "maintenance_margin_pct": 1.0},
    "BNB": {"max_leverage": 50, "maintenance_margin_pct": 1.0},
    "XRP": {"max_leverage": 50, "maintenance_margin_pct": 1.0},
    "DOGE": {"max_leverage": 25, "maintenance_margin_pct": 1.5},
    "LINK": {"max_leverage": 25, "maintenance_margin_pct": 1.5},
    "AVAX": {"max_leverage": 25, "maintenance_margin_pct": 1.5},
    "SUI": {"max_leverage": 20, "maintenance_margin_pct": 2.0},
    "UNI": {"max_leverage": 25, "maintenance_margin_pct": 1.5},
}


def resolve_leverage_bracket(symbol: str) -> dict:
    """Pure function: this symbol's own SIMULATED (max_leverage,
    maintenance_margin_pct) bracket, falling back to the configured
    conservative defaults for any symbol not in the table above (never a
    silent KeyError, never an unlimited leverage default)."""
    settings = get_settings()
    bracket = FUTURES_LEVERAGE_BRACKETS.get(symbol.upper())
    if bracket is not None:
        return bracket
    return {
        "max_leverage": settings.futures_sim_default_max_leverage,
        "maintenance_margin_pct": settings.futures_sim_default_maintenance_margin_pct,
    }


def resolve_max_leverage(symbol: str) -> int:
    """Pure function: the highest leverage this symbol may be opened at."""
    return resolve_leverage_bracket(symbol)["max_leverage"]


def resolve_maintenance_margin_pct(symbol: str) -> float:
    """Pure function: this symbol's own SIMULATED maintenance margin rate,
    as a percent of notional (e.g. 0.4 means 0.4%)."""
    return resolve_leverage_bracket(symbol)["maintenance_margin_pct"]


def available_leverage_options(symbol: str) -> list[int]:
    """Pure function: the selectable leverage list (task: 1x..75x) clamped
    to this symbol's own max_leverage -- never offers a leverage the
    symbol's own bracket forbids, regardless of the global LEVERAGE_OPTIONS
    list."""
    max_leverage = resolve_max_leverage(symbol)
    return [lev for lev in LEVERAGE_OPTIONS if lev <= max_leverage]


def validate_leverage(symbol: str, requested_leverage: int) -> int:
    """Pure function: returns `requested_leverage` unchanged if it's both
    one of the standard LEVERAGE_OPTIONS and within this symbol's own
    bracket max, else raises ValueError with a message identifying which
    constraint failed -- callers (the order API) turn this into a 400,
    never a silent clamp that changes what the user asked for without
    telling them."""
    if requested_leverage not in LEVERAGE_OPTIONS:
        raise ValueError(
            f"{requested_leverage}x is not a supported leverage option "
            f"({', '.join(f'{lev}x' for lev in LEVERAGE_OPTIONS)})"
        )
    max_leverage = resolve_max_leverage(symbol)
    if requested_leverage > max_leverage:
        raise ValueError(
            f"{symbol} max leverage is {max_leverage}x (requested {requested_leverage}x)"
        )
    return requested_leverage


def compute_initial_margin(notional: float, leverage: int) -> float:
    """Pure function: the margin a position of this notional value locks up
    at this leverage -- notional / leverage, the definition of leverage."""
    return notional / leverage


def compute_maintenance_margin(notional: float, maintenance_margin_pct: float) -> float:
    """Pure function: the minimum margin this position must keep before
    liquidation, as a percent of its current notional value."""
    return notional * maintenance_margin_pct / 100


def compute_position_pnl(
    side: str, entry_price: float, mark_price: float, quantity: float
) -> float:
    """Pure function: gross (pre-fee/funding) unrealized or realized PnL.
    LONG profits when mark_price rises above entry_price; SHORT profits
    when it falls below -- the two textbook futures PnL formulas, and nothing
    else (fees/funding are applied separately, see compute_net_pnl)."""
    if side.upper() == "LONG":
        return (mark_price - entry_price) * quantity
    if side.upper() == "SHORT":
        return (entry_price - mark_price) * quantity
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def compute_net_pnl(
    gross_pnl: float, fees: float, funding: float, slippage_cost: float = 0.0
) -> float:
    """Pure function: Net PnL = gross_pnl - fees - funding - slippage_cost
    (task's own formula, verbatim) -- fees/funding/slippage are each
    already signed as a cost (positive number reduces PnL) by their own
    callers, so this is a plain subtraction, never a re-derivation."""
    return gross_pnl - fees - funding - slippage_cost


def compute_roi_pct(pnl: float, margin: float) -> float | None:
    """Pure function: ROI on margin (task: "Margin=$500, Gross PnL=+$100
    -> ROI=+20%") -- distinct from account-equity return, which the caller
    computes separately from the account's own equity curve. None when
    margin is 0 (nothing to divide by, never a fabricated infinite ROI)."""
    if margin == 0:
        return None
    return round(100 * pnl / margin, 4)


def compute_isolated_liquidation_price(
    side: str, entry_price: float, leverage: int, maintenance_margin_pct: float
) -> float:
    """Pure function: ISOLATED-margin liquidation price -- this position's
    own initial margin is the only cushion (task: "margin принадлежит
    конкретной позиции"). Standard simplified futures liquidation formula
    (ignores the exact taker-fee cost of the liquidating fill itself,
    documented as a known simplification in docs/FUTURES_SIMULATOR_MATH.md):

    LONG:  liq_price = entry_price * (1 - 1/leverage + maintenance_margin_pct/100)
    SHORT: liq_price = entry_price * (1 + 1/leverage - maintenance_margin_pct/100)

    Derivation: a position liquidates once its margin balance (initial
    margin +/- unrealized PnL) falls to its maintenance margin. Substituting
    initial_margin = notional/leverage and maintenance_margin =
    notional*maintenance_margin_pct/100, then solving compute_position_pnl
    for the mark_price at which margin_balance == maintenance_margin gives
    exactly the formulas above (the `quantity`/`notional` terms cancel)."""
    maintenance_fraction = maintenance_margin_pct / 100
    if side.upper() == "LONG":
        return entry_price * (1 - 1 / leverage + maintenance_fraction)
    if side.upper() == "SHORT":
        return entry_price * (1 + 1 / leverage - maintenance_fraction)
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def compute_cross_liquidation_price(
    side: str,
    entry_price: float,
    quantity: float,
    initial_margin: float,
    maintenance_margin: float,
    other_account_equity: float,
) -> float:
    """Pure function: CROSS-margin liquidation price -- the rest of the
    account's equity acts as extra cushion beyond this position's own
    initial margin (task: "available account equity участвует в
    поддержании позиций"), so this position liquidates later than the same
    position would in ISOLATED mode whenever `other_account_equity` is
    positive (and earlier if the rest of the account is already underwater
    -- `other_account_equity` can be negative). `other_account_equity` is
    the account's total equity EXCLUDING this position's own initial
    margin and unrealized PnL (wallet_balance + every OTHER open
    position's unrealized PnL) -- the caller (compute_account_state)
    is responsible for excluding this position correctly so the formula
    below isn't circular.

    Derivation: liquidates when (other_account_equity + initial_margin +
    unrealized_pnl) == maintenance_margin. Solving compute_position_pnl for
    the mark_price at that point:

    LONG:  liq_price = entry_price - cushion / quantity
    SHORT: liq_price = entry_price + cushion / quantity
    where cushion = other_account_equity + initial_margin - maintenance_margin
    """
    cushion = other_account_equity + initial_margin - maintenance_margin
    if side.upper() == "LONG":
        return entry_price - cushion / quantity
    if side.upper() == "SHORT":
        return entry_price + cushion / quantity
    raise ValueError(f"side must be LONG or SHORT, got {side!r}")


def compute_fee(notional: float, is_maker: bool) -> dict:
    """Pure function: fee_rate_pct + fee_amount for one fill, from the
    configured (never hardcoded) maker/taker schedule. Returns both the
    rate actually applied and the resulting dollar amount, so an order row
    can honestly record what rate was in effect at fill time even if
    settings change later."""
    settings = get_settings()
    fee_rate_pct = (
        settings.futures_sim_maker_fee_pct if is_maker else settings.futures_sim_taker_fee_pct
    )
    return {"fee_rate_pct": fee_rate_pct, "fee_amount": notional * fee_rate_pct / 100}


def compute_market_fill_price(side: str, reference_price: float) -> dict:
    """Pure function: a MARKET order's simulated fill, applying configured
    slippage against the side that's actually unfavorable to the trader
    (a BUY-to-open-LONG pays slightly MORE than reference_price, a
    SELL-to-open-SHORT receives slightly LESS) -- never slippage that
    favors the trader, matching how real market impact works. Returns
    requested_price/estimated_fill_price/actual_fill_price/slippage_pct
    together (task's own required field set) -- in this deterministic
    simulation estimated and actual are identical (no partial-fill price
    walk yet), kept as two fields so a future more realistic fill model
    can diverge them without a schema change."""
    settings = get_settings()
    slippage_pct = settings.futures_sim_market_slippage_pct
    direction = 1 if side.upper() == "BUY" else -1
    fill_price = reference_price * (1 + direction * slippage_pct / 100)
    return {
        "requested_price": reference_price,
        "estimated_fill_price": fill_price,
        "actual_fill_price": fill_price,
        "slippage_pct": slippage_pct,
    }


def compute_simulated_mark_price(recent_prices: list[float], alpha: float = 0.3) -> float | None:
    """Pure function: SIMULATED MARK PRICE -- deliberately NOT just the
    latest traded price (task's own explicit requirement), computed as an
    exponential moving average over the last few real observed prices
    (oldest to newest) instead. This project has no separate real index-
    price feed to blend with the way a real exchange's mark price does, so
    this EMA smoothing is the honest, documented "configurable simulation
    formula" the task asks for when a real mark price is unavailable --
    every consumer of this value must label it SIMULATED MARK PRICE, never
    present it as sourced from a real exchange. None (never a fabricated
    0.0) when there are no prices to smooth."""
    if not recent_prices:
        return None
    mark = recent_prices[0]
    for price in recent_prices[1:]:
        mark = alpha * price + (1 - alpha) * mark
    return mark


async def get_current_price(
    session_factory: async_sessionmaker[AsyncSession], redis: Redis, symbol: str
) -> dict | None:
    """Real market price for `symbol`, preferring a fresh realtime tick
    (app.services.realtime, Coinbase-sourced) and falling back to the
    latest synced history candle's close (app.services.history) when no
    realtime tick exists or it's gone stale -- the exact same freshness
    classification (`classify_freshness`) the rest of the app already
    uses, not a second staleness concept. Returns None (never a fabricated
    price) when neither source has anything for this symbol. Always
    reports `market_data_timestamp` and `source_provider` (task
    requirement) so a consumer can show exactly how old/where a price
    came from."""
    settings = get_settings()
    ticks = await get_latest_ticks(redis, [symbol.upper()])
    tick = ticks.get(symbol.upper())
    if tick is not None:
        tick_age = age_seconds(tick.event_timestamp)
        freshness = classify_freshness(
            tick_age,
            live_seconds=settings.realtime_freshness_live_seconds,
            recent_seconds=settings.realtime_freshness_recent_seconds,
            delayed_seconds=settings.realtime_freshness_delayed_seconds,
            stale_seconds=settings.realtime_freshness_stale_seconds,
        )
        if freshness not in ("stale", "offline"):
            return {
                "price": tick.price,
                "market_data_timestamp": tick.event_timestamp,
                "source_provider": tick.source,
                "freshness": freshness,
            }

    config = find_symbol_config(symbol)
    if config is None:
        return None
    rows = await get_series(session_factory, config.model, symbol, Timeframe.DAILY)
    if not rows:
        return None
    latest = rows[-1]
    return {
        "price": float(latest.close),
        "market_data_timestamp": latest.timestamp,
        "source_provider": f"{config.provider.__class__.__name__} (history)",
        "freshness": classify_freshness(
            age_seconds(latest.timestamp),
            live_seconds=settings.realtime_freshness_live_seconds,
            recent_seconds=settings.realtime_freshness_recent_seconds,
            delayed_seconds=settings.realtime_freshness_delayed_seconds,
            stale_seconds=settings.realtime_freshness_stale_seconds,
        ),
    }


_MARK_PRICE_EMA_KEY_PREFIX = "futures_sim:mark_ema:"
_MARK_PRICE_EMA_TTL_SECONDS = 3600


async def get_mark_price(
    session_factory: async_sessionmaker[AsyncSession], redis: Redis, symbol: str
) -> dict | None:
    """SIMULATED MARK PRICE (task's own explicit requirement: mark price
    must NOT always just be the last traded price). Wraps get_current_price()
    with the EMA smoothing compute_simulated_mark_price() already
    implements, applied incrementally: the previous EMA value is persisted
    in Redis per symbol (`_MARK_PRICE_EMA_KEY_PREFIX`) and blended with
    each newly observed real reference price, rather than replaying a
    stored price history -- mathematically identical to feeding a growing
    list into compute_simulated_mark_price(), without needing to store one.

    Returns the same shape as get_current_price() plus `reference_price`
    (the real, unsmoothed price get_current_price() returned) and
    `mark_price_simulated: True` -- every consumer MUST surface that flag
    (or an equivalent "SIMULATED MARK PRICE" label) rather than presenting
    the smoothed value as sourced from a real exchange. Returns None
    (never a fabricated mark price) when get_current_price() itself has
    nothing for this symbol."""
    settings = get_settings()
    price_info = await get_current_price(session_factory, redis, symbol)
    if price_info is None:
        return None

    reference_price = price_info["price"]
    key = f"{_MARK_PRICE_EMA_KEY_PREFIX}{symbol.upper()}"
    previous_ema_raw = await redis.get(key)
    if previous_ema_raw is not None:
        previous_ema = float(previous_ema_raw)
        mark_price = (
            settings.futures_sim_mark_price_ema_alpha * reference_price
            + (1 - settings.futures_sim_mark_price_ema_alpha) * previous_ema
        )
    else:
        mark_price = reference_price
    await redis.set(key, str(mark_price), ex=_MARK_PRICE_EMA_TTL_SECONDS)

    return {
        **price_info,
        "price": mark_price,
        "reference_price": reference_price,
        "mark_price_simulated": True,
    }


class FuturesSimEngine:
    """Account-lifecycle service: get-or-create, reset, and live account
    state. Order execution lives in app.services.futures_sim.orders."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], redis: Redis) -> None:
        self._session_factory = session_factory
        self._redis = redis

    async def get_or_create_account(self, name: str = DEFAULT_ACCOUNT_NAME) -> FuturesSimAccount:
        """Returns the one ACTIVE account for `name`, creating it (with a
        fresh `account_session_id` and `wallet_balance` =
        futures_sim_initial_balance_usd) the first time this name is ever
        seen -- task requirement: "При первом открытии: Initial Balance =
        10,000 USDT"."""
        async with self._session_factory() as session:
            account = await session.scalar(
                select(FuturesSimAccount).where(
                    FuturesSimAccount.name == name, FuturesSimAccount.status == "ACTIVE"
                )
            )
            if account is not None:
                return account

            settings = get_settings()
            initial_balance = settings.futures_sim_initial_balance_usd
            account = FuturesSimAccount(
                name=name,
                account_session_id=uuid.uuid4(),
                status="ACTIVE",
                wallet_balance=initial_balance,
                peak_equity=initial_balance,
            )
            session.add(account)
            await session.flush()
            session.add(
                FuturesSimLedgerEntry(
                    account_id=account.id,
                    event_type="DEPOSIT",
                    amount=initial_balance,
                    balance_after=initial_balance,
                    reference_type="ACCOUNT",
                    reference_id=account.id,
                    description=f"Initial demo balance for account {name!r}",
                )
            )
            await session.commit()
            await session.refresh(account)
            return account

    async def reset_account(self, name: str = DEFAULT_ACCOUNT_NAME) -> FuturesSimAccount:
        """Reset Demo Account (task): closes out the current ACTIVE
        account's lifecycle by marking it RESET (never deleted -- old
        sessions stay queryable forever via `account_session_id`) and
        creates a brand-new ACTIVE account for the same `name`, balance
        reset to futures_sim_initial_balance_usd. Does NOT delete open
        positions/orders on the old account -- app.services.futures_sim.
        orders.close_all_positions() should be called first if the caller
        wants a clean reset rather than abandoning open state; this method
        only handles the account-record transition itself."""
        async with self._session_factory() as session:
            old_account = await session.scalar(
                select(FuturesSimAccount).where(
                    FuturesSimAccount.name == name, FuturesSimAccount.status == "ACTIVE"
                )
            )
            now = datetime.now(UTC)
            if old_account is not None:
                old_account.status = "RESET"
                old_account.reset_at = now
                session.add(
                    FuturesSimLedgerEntry(
                        account_id=old_account.id,
                        event_type="RESET",
                        amount=0,
                        balance_after=float(old_account.wallet_balance),
                        reference_type="ACCOUNT",
                        reference_id=old_account.id,
                        description=f"Account {name!r} reset -- new demo session started",
                    )
                )

            settings = get_settings()
            initial_balance = settings.futures_sim_initial_balance_usd
            new_account = FuturesSimAccount(
                name=name,
                account_session_id=uuid.uuid4(),
                status="ACTIVE",
                wallet_balance=initial_balance,
                peak_equity=initial_balance,
            )
            session.add(new_account)
            await session.flush()
            session.add(
                FuturesSimLedgerEntry(
                    account_id=new_account.id,
                    event_type="DEPOSIT",
                    amount=initial_balance,
                    balance_after=initial_balance,
                    reference_type="ACCOUNT",
                    reference_id=new_account.id,
                    description=f"Initial demo balance for new session (account {name!r})",
                )
            )
            await session.commit()
            await session.refresh(new_account)
            return new_account

    async def get_account_state(self, account: FuturesSimAccount) -> dict:
        """Live account state (task: wallet_balance/equity/available_margin/
        used_margin/unrealized_pnl/realized_pnl/fees_paid/funding_paid/
        margin_ratio/maintenance_margin/max_drawdown) -- equity/
        unrealized_pnl/used_margin/available_margin/margin_ratio/
        maintenance_margin_total are ALWAYS derived here from this
        account's own OPEN positions against current mark prices, never
        read from a stale stored column (see FuturesSimAccount's own
        docstring for why). `peak_equity`/`max_drawdown_pct` are ratcheted
        forward on the account row itself when this call finds a new
        equity high -- the one piece of derived state that genuinely needs
        persisting."""
        async with self._session_factory() as session:
            positions = list(
                await session.scalars(
                    select(FuturesSimPosition).where(
                        FuturesSimPosition.account_id == account.id,
                        FuturesSimPosition.status == "OPEN",
                    )
                )
            )

        unrealized_pnl = 0.0
        used_margin = 0.0
        maintenance_margin_total = 0.0
        position_states = []
        for position in positions:
            # SIMULATED MARK PRICE (task: never just the last traded
            # price) -- unrealized PnL, equity, and margin ratio are all
            # driven by mark price on a real exchange too, so this uses
            # the same smoothed value get_mark_price() computes, not the
            # raw reference price. Liquidation/SL/TP trigger checks
            # (app.services.futures_sim.monitor) deliberately still use
            # the raw reference price -- see that module's own docstring.
            price_info = await get_mark_price(self._session_factory, self._redis, position.symbol)
            mark_price = (
                price_info["price"] if price_info is not None else float(position.mark_price)
            )
            pnl = compute_position_pnl(
                position.side, float(position.entry_price), mark_price, float(position.quantity)
            )
            unrealized_pnl += pnl
            used_margin += float(position.initial_margin)
            maintenance_margin_total += float(position.maintenance_margin)
            position_states.append(
                {"position": position, "mark_price": mark_price, "unrealized_pnl": pnl}
            )

        wallet_balance = float(account.wallet_balance)
        equity = wallet_balance + unrealized_pnl
        available_margin = equity - used_margin
        margin_ratio = round(100 * used_margin / equity, 4) if equity > 0 else None

        peak_equity = max(float(account.peak_equity), equity)
        max_drawdown_pct = float(account.max_drawdown_pct)
        if peak_equity > 0:
            current_drawdown_pct = round(100 * (peak_equity - equity) / peak_equity, 4)
            max_drawdown_pct = max(max_drawdown_pct, current_drawdown_pct)
        if peak_equity != float(account.peak_equity) or max_drawdown_pct != float(
            account.max_drawdown_pct
        ):
            async with self._session_factory() as session:
                db_account = await session.get(FuturesSimAccount, account.id)
                db_account.peak_equity = peak_equity
                db_account.max_drawdown_pct = max_drawdown_pct
                await session.commit()

        return {
            "name": account.name,
            "account_session_id": str(account.account_session_id),
            "status": account.status,
            "wallet_balance": wallet_balance,
            "equity": equity,
            "available_margin": available_margin,
            "used_margin": used_margin,
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl_total": float(account.realized_pnl_total),
            "fees_paid_total": float(account.fees_paid_total),
            "funding_paid_total": float(account.funding_paid_total),
            "maintenance_margin_total": maintenance_margin_total,
            "margin_ratio": margin_ratio,
            "peak_equity": peak_equity,
            "max_drawdown_pct": max_drawdown_pct,
            "open_position_count": len(positions),
            "created_at": account.created_at,
            "reset_at": account.reset_at,
        }


def build_futures_sim_engine() -> FuturesSimEngine:
    from app.database.redis import get_redis
    from app.database.session import get_session_factory

    return FuturesSimEngine(get_session_factory(), get_redis())
