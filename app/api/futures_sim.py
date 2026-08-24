"""Futures Simulator API -- 100% demo/paper trading, no real money, no real
exchange orders. Every mutating endpoint is gated by require_admin_key, the
same single-shared-key mechanism app/api/portfolio.py and app/api/admin.py
already use (this project has no user/auth model at all -- see
FuturesSimAccount's own docstring). Read endpoints stay open, matching how
every other read endpoint in this app already behaves."""

from fastapi import APIRouter, Depends

from app.api.admin import require_admin_key
from app.config import get_settings
from app.services.futures_sim.engine import (
    DEFAULT_ACCOUNT_NAME,
    available_leverage_options,
    build_futures_sim_engine,
    resolve_leverage_bracket,
)
from app.services.realtime.config import parse_watchlist

router = APIRouter(prefix="/api/simulator", tags=["futures-simulator"])


def _serialize_account_state(state: dict) -> dict:
    return {
        **{k: v for k, v in state.items() if k not in ("created_at", "reset_at")},
        "created_at": state["created_at"].isoformat(),
        "reset_at": state["reset_at"].isoformat() if state["reset_at"] is not None else None,
        "paper_trading": True,
        "real_funds_used": False,
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
