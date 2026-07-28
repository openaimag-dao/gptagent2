from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.alerts.rules import VALID_METRICS, VALID_OPERATORS, build_alert_rule_engine

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class CreateAlertRuleRequest(BaseModel):
    chat_id: str
    symbol: str
    metric: str
    operator: str
    threshold: float
    cooldown_minutes: int = 60


def _serialize_rule(rule) -> dict:
    return {
        "id": rule.id,
        "chat_id": rule.chat_id,
        "symbol": rule.symbol,
        "metric": rule.metric,
        "operator": rule.operator,
        "threshold": float(rule.threshold),
        "cooldown_minutes": rule.cooldown_minutes,
        "enabled": rule.enabled,
        "created_at": rule.created_at.isoformat(),
        "last_triggered_at": (
            rule.last_triggered_at.isoformat() if rule.last_triggered_at is not None else None
        ),
    }


@router.get("/metrics")
async def list_metrics() -> dict:
    return {"metrics": list(VALID_METRICS), "operators": list(VALID_OPERATORS)}


@router.post("/rules")
async def create_rule(request: CreateAlertRuleRequest) -> dict:
    engine = build_alert_rule_engine()
    try:
        rule = await engine.create_rule(
            request.chat_id,
            request.symbol,
            request.metric,
            request.operator,
            request.threshold,
            request.cooldown_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_rule(rule)


@router.get("/rules")
async def get_rules(chat_id: str = Query(...)) -> dict:
    engine = build_alert_rule_engine()
    rules = await engine.list_rules(chat_id)
    return {"rules": [_serialize_rule(r) for r in rules]}


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int, chat_id: str = Query(...)) -> dict:
    engine = build_alert_rule_engine()
    removed = await engine.delete_rule(rule_id, chat_id)
    if not removed:
        raise HTTPException(
            status_code=404, detail=f"No rule with id {rule_id} owned by chat {chat_id}"
        )
    return {"removed": True, "rule_id": rule_id}


@router.get("/history")
async def get_history(chat_id: str = Query(...), limit: int = Query(20, ge=1, le=200)) -> dict:
    engine = build_alert_rule_engine()
    history = await engine.recent_history(chat_id, limit)
    return {"history": history}
