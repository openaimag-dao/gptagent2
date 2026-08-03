"""Scenario Engine -- instead of one predicted future, generates a small
set of named, probability-weighted scenarios. Every probability is a
deterministic, documented weighting of the Global Market Score's already-
computed sub-scores (themselves traceable to real regime/signal inputs) --
never an LLM-invented number. Weights are normalized to sum to 100.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import GlobalMarketScore, ScenarioSnapshot
from app.services.global_score.engine import GlobalScoreEngine

logger = logging.getLogger(__name__)

# Tail-risk scenarios are structurally dampened relative to the other three
# even under maximum stress inputs -- a black swan is rare by definition,
# not just "whatever's left over" after the other three are computed.
_BLACK_SWAN_DAMPENING = 0.25
_MIN_SCENARIO_WEIGHT = 3.0

_SCENARIOS: tuple[str, ...] = ("soft_landing", "risk_off", "liquidity_expansion", "black_swan")

_SCENARIO_LABELS: dict[str, str] = {
    "soft_landing": "Soft Landing",
    "risk_off": "Risk Off",
    "liquidity_expansion": "Liquidity Expansion",
    "black_swan": "Black Swan",
}

_BEARISH_SCENARIO_KEYS = ("risk_off", "black_swan")
_BULLISH_SCENARIO_KEYS = ("soft_landing", "liquidity_expansion")

# Plain-English threat label from the combined risk_off + black_swan
# probability -- fixed, documented thresholds on numbers the engine already
# computed, never a new probability model of its own.
_THREAT_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (50.0, "Severe"),
    (35.0, "Elevated"),
    (20.0, "Moderate"),
)
_DEFAULT_THREAT_LEVEL = "Low"


def _raw_weights(score: GlobalMarketScore) -> dict[str, float]:
    soft_landing = (
        0.5 * score.risk_on_score
        + 0.3 * (100 - score.macro_pressure_score)
        + 0.2 * score.greed_score
    )
    risk_off = (
        0.5 * score.risk_off_score + 0.3 * score.macro_pressure_score + 0.2 * score.fear_score
    )
    liquidity_expansion = 0.6 * score.liquidity_score + 0.4 * score.risk_on_score
    black_swan = (
        0.4 * score.fear_score + 0.3 * score.macro_pressure_score + 0.3 * score.risk_off_score
    ) * _BLACK_SWAN_DAMPENING

    return {
        "soft_landing": max(soft_landing, _MIN_SCENARIO_WEIGHT),
        "risk_off": max(risk_off, _MIN_SCENARIO_WEIGHT),
        "liquidity_expansion": max(liquidity_expansion, _MIN_SCENARIO_WEIGHT),
        "black_swan": max(black_swan, _MIN_SCENARIO_WEIGHT),
    }


def _rationale(name: str, score: GlobalMarketScore) -> str:
    if name == "soft_landing":
        return (
            f"Risk-On {score.risk_on_score}/100, macro pressure {score.macro_pressure_score}/100, "
            f"greed {score.greed_score}/100 -- growth continues without a liquidity or macro shock."
        )
    if name == "risk_off":
        return (
            f"Risk-Off {score.risk_off_score}/100, "
            f"macro pressure {score.macro_pressure_score}/100, "
            f"fear {score.fear_score}/100 -- broad de-risking across crypto and equities."
        )
    if name == "liquidity_expansion":
        return (
            f"Liquidity {score.liquidity_score}/100, Risk-On {score.risk_on_score}/100 -- "
            "easing monetary conditions lift risk assets broadly."
        )
    return (
        f"Fear {score.fear_score}/100, macro pressure {score.macro_pressure_score}/100, "
        f"Risk-Off {score.risk_off_score}/100 -- tail-risk weight, dampened by design since a "
        "genuine black swan is rare regardless of how stressed current sub-scores read."
    )


def compute_scenarios(score: GlobalMarketScore) -> list[dict]:
    """Pure function: GlobalMarketScore -> 4 named scenarios whose
    probabilities sum to exactly 100."""
    raw = _raw_weights(score)
    total = sum(raw.values())
    probabilities = {name: round(100 * weight / total) for name, weight in raw.items()}

    # Fix any rounding drift so probabilities sum to exactly 100 -- adjust
    # whichever scenario has the largest weight (largest-remainder-adjacent,
    # deterministic and stable).
    drift = 100 - sum(probabilities.values())
    if drift != 0:
        largest = max(raw, key=raw.get)
        probabilities[largest] += drift

    return [
        {
            "name": _SCENARIO_LABELS[name],
            "key": name,
            "probability_pct": probabilities[name],
            "rationale": _rationale(name, score),
        }
        for name in _SCENARIOS
    ]


def scenario_extremes(scenarios: list[dict] | None) -> tuple:
    """Pure function: the 4-scenario list -> (top_name, top_pct,
    highest_risk, biggest_opportunity). `highest_risk`/`biggest_opportunity`
    are one-line "{name} ({pct}%) -- {rationale}" strings built from the
    highest-probability member of the bearish (risk_off/black_swan) and
    bullish (soft_landing/liquidity_expansion) buckets respectively.

    Originally private to WatchdogEngine (`_scenario_extremes`); lifted out
    here so any caller that already has a scenarios list -- Report
    Generator, ExplanationEngine's alternative_view, Market Scanner --
    reuses this exact opportunity/threat framing instead of picking a
    plain 2nd-ranked scenario or reimplementing the bearish/bullish split.
    """
    if not scenarios:
        return None, None, None, None
    top = max(scenarios, key=lambda s: s["probability_pct"])
    bearish = [s for s in scenarios if s["key"] in _BEARISH_SCENARIO_KEYS]
    bullish = [s for s in scenarios if s["key"] in _BULLISH_SCENARIO_KEYS]
    highest_risk = None
    if bearish:
        r = max(bearish, key=lambda s: s["probability_pct"])
        highest_risk = f"{r['name']} ({r['probability_pct']}%) -- {r['rationale']}"
    biggest_opportunity = None
    if bullish:
        o = max(bullish, key=lambda s: s["probability_pct"])
        biggest_opportunity = f"{o['name']} ({o['probability_pct']}%) -- {o['rationale']}"
    return top["name"], top["probability_pct"], highest_risk, biggest_opportunity


def scenario_threat_level(scenarios: list[dict] | None) -> str | None:
    """Pure function: the 4-scenario list -> a plain-English threat label
    (Low/Moderate/Elevated/Severe) from the combined risk_off + black_swan
    probability. Same bearish bucket `scenario_extremes` already uses for
    `highest_risk` -- this just names the magnitude instead of the scenario."""
    if not scenarios:
        return None
    bearish_pct = sum(s["probability_pct"] for s in scenarios if s["key"] in _BEARISH_SCENARIO_KEYS)
    for threshold, label in _THREAT_THRESHOLDS:
        if bearish_pct >= threshold:
            return label
    return _DEFAULT_THREAT_LEVEL


class ScenarioEngine:
    """Computes and persists the current scenario set from the latest
    Global Market Score (computed fresh each call, same convention as
    GlobalScoreEngine itself)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        global_score_engine: GlobalScoreEngine,
    ) -> None:
        self._session_factory = session_factory
        self._global_score_engine = global_score_engine

    async def compute_and_store(self) -> ScenarioSnapshot | None:
        score = await self._global_score_engine.compute_and_store()
        if score is None:
            return None

        scenarios = compute_scenarios(score)
        row = ScenarioSnapshot(scenarios=scenarios, global_score=score.global_score)
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def get_latest(self) -> ScenarioSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(ScenarioSnapshot).order_by(ScenarioSnapshot.computed_at.desc()).limit(1)
            )
