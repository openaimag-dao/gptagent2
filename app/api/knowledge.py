from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.database.models import KnowledgeRule, RuleCategory
from app.database.session import get_session_factory
from app.services.backtest.conditions import Condition
from app.services.history.registry import find_symbol_config
from app.services.history.schemas import Timeframe
from app.services.knowledge.engine import KnowledgeEngine
from app.services.knowledge.rules import RuleEngine

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class ConditionRequest(BaseModel):
    symbol: str
    field: str
    operator: str
    value: float


class CreateRuleRequest(BaseModel):
    title: str
    description: str
    category: RuleCategory
    author: str
    target_symbol: str
    conditions: list[ConditionRequest] = Field(min_length=1)
    horizon_periods: int = Field(default=1, ge=1)


def _serialize_rule(rule: KnowledgeRule) -> dict:
    return {
        "id": rule.id,
        "title": rule.title,
        "description": rule.description,
        "category": rule.category.value,
        "author": rule.author,
        "target_symbol": rule.target_symbol,
        "conditions": rule.conditions,
        "horizon_periods": rule.horizon_periods,
        "occurrences": rule.occurrences,
        "win_rate_pct": float(rule.win_rate_pct) if rule.win_rate_pct is not None else None,
        "avg_return_pct": (
            float(rule.avg_return_pct) if rule.avg_return_pct is not None else None
        ),
        "max_drawdown_pct": (
            float(rule.max_drawdown_pct) if rule.max_drawdown_pct is not None else None
        ),
        "profit_factor": float(rule.profit_factor) if rule.profit_factor is not None else None,
        "sharpe_ratio": float(rule.sharpe_ratio) if rule.sharpe_ratio is not None else None,
        "confidence_pct": rule.confidence_pct,
        "last_backtested_at": (
            rule.last_backtested_at.isoformat() if rule.last_backtested_at is not None else None
        ),
        "created_at": rule.created_at.isoformat(),
    }


@router.post("/rules")
async def create_rule(request: CreateRuleRequest) -> dict:
    try:
        conditions = [
            Condition(symbol=c.symbol.upper(), field=c.field, operator=c.operator, value=c.value)
            for c in request.conditions
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    engine = RuleEngine(get_session_factory())
    rule = await engine.create_rule(
        request.title,
        request.description,
        request.category,
        request.author,
        request.target_symbol,
        conditions,
        request.horizon_periods,
    )
    return _serialize_rule(rule)


@router.get("/rules")
async def list_rules() -> dict:
    engine = RuleEngine(get_session_factory())
    rules = await engine.list_rules()
    return {"count": len(rules), "rules": [_serialize_rule(r) for r in rules]}


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: int) -> dict:
    engine = RuleEngine(get_session_factory())
    rule = await engine.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"No rule with id {rule_id}")
    return _serialize_rule(rule)


@router.post("/rules/{rule_id}/backtest")
async def rerun_rule_backtest(rule_id: int) -> dict:
    engine = RuleEngine(get_session_factory())
    rule = await engine.backtest_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"No rule with id {rule_id}")
    return _serialize_rule(rule)


@router.get("/{symbol}")
async def get_knowledge(
    symbol: str,
    timeframe: str = Query("1d", description="1d, 4h or 1h"),
    k: int = Query(5, ge=1, le=20),
) -> dict:
    config = find_symbol_config(symbol)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Unknown historical symbol: {symbol}")

    try:
        tf = Timeframe(timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {timeframe}") from exc

    engine = KnowledgeEngine(get_session_factory())
    analogs = await engine.find_analogs(config.symbol, config.model, tf, k=k)
    if not analogs:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Not enough synced history for {config.symbol}/{timeframe} to find analogs "
                "yet -- run sync_history.py first"
            ),
        )

    return {
        "symbol": config.symbol,
        "timeframe": timeframe,
        "analogs": [
            {
                "timestamp": a["timestamp"].isoformat(),
                "rsi": a["rsi"],
                "volatility": a["volatility"],
                "distance": a["distance"],
                "forward_return_pct": a["forward_return_pct"],
                "nearby_events": a["nearby_events"],
            }
            for a in analogs
        ],
    }
