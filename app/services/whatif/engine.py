"""WhatIfSimulator -- the I/O layer around app.services.whatif.scenarios:
resolves each named shock's data source (historical event study,
correlation direction, or heuristic) using engines this platform already
has (EventImpactEngine, CorrelationEngine, RegimeDetector,
GlobalScoreEngine, ProbabilityEngine), and assembles the result. Read-only
against already-scheduled engines' latest computed rows -- this is a
what-if lens over existing data, not a new source of truth, so nothing
here is persisted.
"""

import asyncio
from datetime import UTC, datetime

from app.services.analysis.correlation import CorrelationEngine
from app.services.analysis.regime import RegimeDetector
from app.services.global_score.engine import GlobalScoreEngine
from app.services.history.schemas import Timeframe
from app.services.probability.engine import ProbabilityEngine
from app.services.research.impact import EventImpactEngine
from app.services.whatif.scenarios import (
    SHOCKS,
    SHOCKS_BY_KEY,
    ShockDefinition,
    average_forward_return,
    correlation_direction,
)

_IMPACT_SYMBOLS: tuple[str, ...] = ("BTC", "ETH", "SOL")
_CORRELATION_WINDOW_DAYS = 30


class WhatIfSimulator:
    def __init__(
        self,
        event_impact_engine: EventImpactEngine,
        correlation_engine: CorrelationEngine,
        regime_detector: RegimeDetector,
        global_score_engine: GlobalScoreEngine,
        probability_engine: ProbabilityEngine,
    ) -> None:
        self._event_impact_engine = event_impact_engine
        self._correlation_engine = correlation_engine
        self._regime_detector = regime_detector
        self._global_score_engine = global_score_engine
        self._probability_engine = probability_engine

    def list_scenarios(self) -> list[dict]:
        return [
            {"key": shock.key, "label": shock.label, "description": shock.description}
            for shock in SHOCKS
        ]

    async def _historical_impact(self, shock: ShockDefinition) -> tuple[dict, str]:
        # One independent read per symbol -- gathered rather than sequential.
        occurrences_by_symbol = await asyncio.gather(
            *(
                self._event_impact_engine.measure_impact(shock.event_category, symbol)
                for symbol in _IMPACT_SYMBOLS
            )
        )

        impact: dict = {}
        max_sample = 0
        for symbol, occurrences in zip(_IMPACT_SYMBOLS, occurrences_by_symbol, strict=True):
            avg, sample_size = average_forward_return(occurrences)
            impact[symbol] = {"expected_return_7d_pct": avg, "sample_size": sample_size}
            max_sample = max(max_sample, sample_size)

        if max_sample == 0:
            return {}, "heuristic_illustrative"

        eth = impact["ETH"]["expected_return_7d_pct"]
        sol = impact["SOL"]["expected_return_7d_pct"]
        alt_values = [v for v in (eth, sol) if v is not None]
        impact["altcoins"] = {
            "expected_return_7d_pct": (
                round(sum(alt_values) / len(alt_values), 2) if alt_values else None
            ),
            "note": "average of ETH/SOL empirical returns -- proxy for altcoins",
        }
        return impact, "historical_event_study"

    async def _correlation_impact(self, shock: ShockDefinition) -> tuple[dict, str]:
        correlations = await self._correlation_engine.get_latest()
        row = next(
            (
                c
                for c in correlations
                if c.window_days == _CORRELATION_WINDOW_DAYS
                and {c.symbol_a, c.symbol_b} == {"BTC", shock.correlation_symbol}
            ),
            None,
        )
        correlation_value = float(row.correlation) if row is not None else None
        if correlation_value is None:
            return {}, "heuristic_illustrative"

        direction = correlation_direction(correlation_value, shock.correlation_shock_sign)
        impact = {
            "BTC": {"direction": direction, "correlation_30d": correlation_value},
            "altcoins": {
                "direction": direction,
                "correlation_30d": None,
                "note": (
                    f"no direct ETH/SOL-{shock.correlation_symbol} correlation is tracked; "
                    "using the BTC-derived direction as a proxy"
                ),
            },
        }
        return impact, "correlation_direction"

    async def simulate(self, scenario_key: str) -> dict | None:
        shock = SHOCKS_BY_KEY.get(scenario_key)
        if shock is None:
            return None

        if shock.event_category is not None:
            impact, data_source = await self._historical_impact(shock)
        elif shock.correlation_symbol is not None:
            impact, data_source = await self._correlation_impact(shock)
        else:
            impact, data_source = {}, "heuristic_illustrative"

        regime_snapshot, global_score, probability_snapshot = await asyncio.gather(
            self._regime_detector.get_latest(),
            self._global_score_engine.get_latest(),
            self._probability_engine.get_latest("BTC", Timeframe.DAILY),
        )

        return {
            "scenario_key": shock.key,
            "scenario_label": shock.label,
            "description": shock.description,
            "data_source": data_source,
            "impact": impact,
            "current_regime": (
                regime_snapshot.regime.value if regime_snapshot is not None else None
            ),
            "likely_regime_shift_toward": shock.regime_shift_toward,
            "risk_direction": shock.risk_direction,
            "liquidity_direction": shock.liquidity_direction,
            "current_risk_off_score": (
                global_score.risk_off_score if global_score is not None else None
            ),
            "current_liquidity_score": (
                global_score.liquidity_score if global_score is not None else None
            ),
            "current_btc_probability": (
                {
                    "up": probability_snapshot.prob_up_pct,
                    "down": probability_snapshot.prob_down_pct,
                    "flat": probability_snapshot.prob_flat_pct,
                }
                if probability_snapshot is not None
                else None
            ),
            "reasoning": shock.heuristic_note,
            "computed_at": datetime.now(UTC).isoformat(),
        }
