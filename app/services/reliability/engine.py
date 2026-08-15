"""Agent Reliability Engine -- tracks each specialist agent's direction call
against what BTC's price actually did next, the same macro/market-wide proxy
every agent's direction already speaks to (see the Consensus Engine's own
documented limitation: these are macro-wide reads, not per-symbol calls).
Reuses LearningEngine's `realized_direction()` rather than reimplementing
"what actually happened" a second time -- this module only adds "who called
it correctly", the same append-only, evaluate-once-the-horizon-elapses
pattern LearningEngine already uses for ProbabilitySnapshot, applied to
agents instead of probability predictions.

Never fabricates a reliability score: an agent with zero evaluable
predictions yet is simply absent from the returned dict, not defaulted to
some baseline accuracy.

V9 Increment 8 hardens the accuracy estimate itself (still returned as the
exact same {agent_name: accuracy_pct} shape ConsensusEngine already
consumes) with two real-but-honest adjustments:
  - Bayesian shrinkage toward an uninformative 50% prior, so an agent with
    only 1-2 evaluated calls isn't treated as confidently 0% or 100%
    accurate off a tiny sample.
  - Recency (half-life) decay, so a stale track record from months ago
    counts for less than this week's calls -- an agent's reliability score
    tracks its CURRENT edge, not a diluted all-time average.
Explicitly NOT implemented here (see this module's own docstring for why
this is the honest boundary, not a gap): inter-agent correlation/redundancy
discounting (no existing infrastructure measures agent-vs-agent vote
correlation; would need a new historical vote-correlation matrix, a
materially larger subsystem than this module's scope).

POST-V9 Phase 5 extends (not replaces) the flat, agent-global accuracy
above with `evaluate_reliability_hierarchical`, which conditions accuracy
on (symbol, horizon, regime) with a hierarchical fallback ladder --
agent+symbol+horizon+regime -> agent+horizon+regime -> agent+horizon ->
agent-global -> 50% prior -- shrinking to a broader level whenever the
narrower one's recency-weighted sample is too small to trust. Honesty
note on the two structural limits this ladder inherits from the rest of
the codebase rather than fixing (fixing them is a separate, larger
project, not this increment's scope): every agent's direction call is a
macro/BTC-proxy read with no symbol attached anywhere in
`AgentOrchestrator`/`AgentPredictionLog`, so the `symbol` tier of the
ladder is structurally unreachable with today's data (always falls
through to the symbol-less levels); and `horizon_periods` is a hardcoded
constant (`_HORIZON_PERIODS = 1`) set in `.log()`, so today only the
`regime` tier can show real differentiation. Both dimensions are wired
through in full so the ladder activates automatically, with no further
changes to this module, the day agents/predictions become genuinely
per-symbol or multi-horizon.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import AgentPredictionLog, CryptoHistory, MarketRegimeSnapshot
from app.services.agents.base import AgentOutput
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.learning.engine import realized_direction

_REFERENCE_SYMBOL = "BTC"
_HORIZON_PERIODS = 1
_PRIOR_ACCURACY_PCT = 50.0

_DIRECTION_TO_PREDICTED = {"bullish": "up", "bearish": "down", "neutral": "flat"}

# (symbol, horizon_periods, regime) key used by the hierarchical fallback
# ladder. symbol is always None in the live pipeline today -- see module
# docstring -- but is part of the key shape so a future symbol-aware
# caller needs no change to this module.
_HierarchyKey = tuple[str | None, int | None, str | None]


def _decayed_weighted_correct(
    results: list[tuple[bool, datetime]], reference_time: datetime, half_life_days: float
) -> tuple[float, float]:
    """Pure helper shared by compute_shrunk_reliability_pct and
    compute_hierarchical_reliability_pct: (correct, timestamp) history ->
    (recency-weighted correct count, total recency weight), each result
    weighted by 0.5 ** (age_days / half_life_days) so older calls count for
    exponentially less."""
    weighted_correct = 0.0
    total_weight = 0.0
    for correct, timestamp in results:
        age_days = max((reference_time - timestamp).total_seconds() / 86400, 0.0)
        weight = 0.5 ** (age_days / half_life_days) if half_life_days > 0 else 1.0
        weighted_correct += weight * (1.0 if correct else 0.0)
        total_weight += weight
    return weighted_correct, total_weight


def compute_shrunk_reliability_pct(
    results: list[tuple[bool, datetime]],
    reference_time: datetime,
    half_life_days: float,
    pseudo_count: float,
    prior_pct: float = _PRIOR_ACCURACY_PCT,
) -> float | None:
    """Pure function: an agent's (correct, prediction_timestamp) history ->
    one recency-decayed, shrinkage-adjusted accuracy percentage. Each result
    is weighted by 0.5 ** (age_days / half_life_days) -- older calls count
    for exponentially less -- then the decayed correct-fraction is pulled
    toward `prior_pct` by `pseudo_count` pseudo-observations (standard
    Bayesian-Beta-style shrinkage: a small decayed sample stays close to the
    prior, a large one is barely moved off its own raw accuracy). None
    (never a guessed score) when `results` is empty."""
    if not results:
        return None

    weighted_correct, total_weight = _decayed_weighted_correct(
        results, reference_time, half_life_days
    )
    if total_weight == 0:
        return prior_pct

    raw_fraction = weighted_correct / total_weight
    shrunk_fraction = (raw_fraction * total_weight + (prior_pct / 100.0) * pseudo_count) / (
        total_weight + pseudo_count
    )
    return round(100 * shrunk_fraction, 1)


def compute_hierarchical_reliability_pct(
    keyed_results: dict[_HierarchyKey, list[tuple[bool, datetime]]],
    key: _HierarchyKey,
    reference_time: datetime,
    half_life_days: float,
    pseudo_count: float,
    min_effective_sample: float,
    prior_pct: float = _PRIOR_ACCURACY_PCT,
) -> dict:
    """Pure function: an agent's results pre-bucketed by (symbol, horizon,
    regime) key -> one accuracy estimate, falling back through
    (symbol, horizon, regime) -> (None, horizon, regime) -> (None, horizon,
    None) -> (None, None, None) whenever a level's recency-weighted
    effective sample size is below `min_effective_sample`, finally
    returning the uninformative `prior_pct` if every level is too thin.
    The symbol-specific level is only attempted when `key`'s symbol is not
    None -- when it is (always, in today's live pipeline; see module
    docstring), that level would be an exact duplicate of the
    (None, horizon, regime) level, and reporting it as
    "symbol_horizon_regime" would misleadingly claim symbol-specific
    evidence that was never actually used. Reuses the exact same
    recency-decay + Bayesian-shrinkage math as `compute_shrunk_reliability_pct`
    (via `_decayed_weighted_correct`) -- this is that same estimate applied
    per-level, not a different algorithm. Always reports which level was
    actually used (`level`) and its effective sample size, so a caller
    never mistakes a heavily-fallen-back estimate for a precise
    regime-specific one."""
    symbol, horizon, regime = key
    ladder: list[tuple[str, _HierarchyKey]] = []
    if symbol is not None:
        ladder.append(("symbol_horizon_regime", (symbol, horizon, regime)))
    ladder.extend(
        [
            ("horizon_regime", (None, horizon, regime)),
            ("horizon", (None, horizon, None)),
            ("global", (None, None, None)),
        ]
    )
    for level, level_key in ladder:
        results = keyed_results.get(level_key)
        if not results:
            continue
        weighted_correct, total_weight = _decayed_weighted_correct(
            results, reference_time, half_life_days
        )
        if total_weight < min_effective_sample:
            continue
        shrunk_fraction = (weighted_correct + (prior_pct / 100.0) * pseudo_count) / (
            total_weight + pseudo_count
        )
        return {
            "accuracy_pct": round(100 * shrunk_fraction, 1),
            "level": level,
            "effective_sample_size": round(total_weight, 2),
        }
    return {"accuracy_pct": prior_pct, "level": "prior", "effective_sample_size": 0.0}


def _evaluated_predictions(
    logs: list[AgentPredictionLog],
    index_by_timestamp: dict[datetime, int],
    rows: list,
) -> list[tuple[str, bool, datetime, int, str | None]]:
    """Pure join: prediction log rows + realized BTC closes -> one
    (agent, correct, reference_timestamp, horizon_periods,
    regime_at_prediction) tuple per prediction whose horizon has actually
    elapsed in stored history. Shared by evaluate_reliability() and
    evaluate_reliability_hierarchical() so this "what actually happened"
    join exists in exactly one place."""
    evaluated: list[tuple[str, bool, datetime, int, str | None]] = []
    for log in logs:
        idx = index_by_timestamp.get(log.reference_timestamp)
        if idx is None:
            continue
        target_idx = idx + log.horizon_periods
        if target_idx >= len(rows):
            continue  # horizon hasn't elapsed in stored history yet

        reference_close = float(rows[idx].close)
        target_close = float(rows[target_idx].close)
        if reference_close == 0:
            continue
        realized_return_pct = 100 * (target_close - reference_close) / reference_close
        realized = realized_direction(realized_return_pct)
        predicted = _DIRECTION_TO_PREDICTED.get(log.direction)
        if predicted is None:
            continue
        evaluated.append(
            (
                log.agent,
                predicted == realized,
                log.reference_timestamp,
                log.horizon_periods,
                log.regime_at_prediction,
            )
        )
    return evaluated


class AgentReliabilityEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def log(self, agent_outputs: dict[str, AgentOutput]) -> None:
        """Appends one row per agent that reported a direction this cycle,
        referenced against BTC's latest synced daily close -- never logs an
        agent with no direction (nothing to evaluate later). Also captures
        the market regime active at logging time (see
        MarketRegimeSnapshot), null if no regime has ever been computed
        yet, so evaluate_reliability_hierarchical() can later condition
        accuracy on regime."""
        rows = await get_series(
            self._session_factory, CryptoHistory, _REFERENCE_SYMBOL, Timeframe.DAILY
        )
        if not rows:
            return
        reference_timestamp = rows[-1].timestamp

        async with self._session_factory() as session:
            latest_regime = await session.scalar(
                select(MarketRegimeSnapshot.regime)
                .order_by(MarketRegimeSnapshot.computed_at.desc())
                .limit(1)
            )
            regime_at_prediction = latest_regime.value if latest_regime is not None else None

            entries = [
                AgentPredictionLog(
                    agent=name,
                    direction=output.direction,
                    confidence=output.confidence,
                    reference_timestamp=reference_timestamp,
                    horizon_periods=_HORIZON_PERIODS,
                    regime_at_prediction=regime_at_prediction,
                )
                for name, output in agent_outputs.items()
                if output.direction is not None
            ]
            if not entries:
                return
            session.add_all(entries)
            await session.commit()

    async def evaluate_reliability(self) -> dict[str, float]:
        """Returns {agent_name: accuracy_pct} for every agent with at least
        one prediction whose horizon has actually elapsed in stored BTC
        history. Agents with none yet are absent, not defaulted. The
        percentage itself is recency-decayed and shrinkage-adjusted (see
        `compute_shrunk_reliability_pct`), not a flat lifetime average."""
        rows = await get_series(
            self._session_factory, CryptoHistory, _REFERENCE_SYMBOL, Timeframe.DAILY
        )
        if not rows:
            return {}
        index_by_timestamp = {row.timestamp: i for i, row in enumerate(rows)}
        reference_time = rows[-1].timestamp

        async with self._session_factory() as session:
            logs = list(await session.scalars(select(AgentPredictionLog)))

        evaluated = _evaluated_predictions(logs, index_by_timestamp, rows)
        results_by_agent: dict[str, list[tuple[bool, datetime]]] = {}
        for agent, correct, timestamp, _horizon, _regime in evaluated:
            results_by_agent.setdefault(agent, []).append((correct, timestamp))

        settings = get_settings()
        scores = {
            agent: compute_shrunk_reliability_pct(
                results,
                reference_time,
                settings.reliability_recency_half_life_days,
                settings.reliability_shrinkage_pseudo_count,
            )
            for agent, results in results_by_agent.items()
            if results
        }
        return {agent: pct for agent, pct in scores.items() if pct is not None}

    async def evaluate_reliability_hierarchical(
        self,
        horizon_periods: int | None = None,
        regime: str | None = None,
        symbol: str | None = None,
    ) -> dict[str, dict]:
        """Same evaluated-prediction pool as evaluate_reliability(), but
        keyed by (symbol, horizon_periods, regime) with the hierarchical
        fallback ladder described in this module's docstring: a narrow
        slice is only used if its recency-weighted effective sample size
        clears `settings.reliability_hierarchical_min_effective_sample`;
        otherwise this shrinks to a broader level, down to an
        uninformative 50% prior. `symbol` and `horizon_periods` default to
        None/the module's single hardcoded horizon respectively since
        neither dimension varies in the live pipeline today (see module
        docstring) -- the parameters exist so a future symbol/horizon-aware
        caller needs no change here. Returns
        {agent_name: {"accuracy_pct", "level", "effective_sample_size"}}
        for every agent with at least one evaluated prediction."""
        rows = await get_series(
            self._session_factory, CryptoHistory, _REFERENCE_SYMBOL, Timeframe.DAILY
        )
        if not rows:
            return {}
        index_by_timestamp = {row.timestamp: i for i, row in enumerate(rows)}
        reference_time = rows[-1].timestamp

        async with self._session_factory() as session:
            logs = list(await session.scalars(select(AgentPredictionLog)))

        evaluated = _evaluated_predictions(logs, index_by_timestamp, rows)

        keyed_by_agent: dict[str, dict[_HierarchyKey, list[tuple[bool, datetime]]]] = {}
        for agent, correct, timestamp, log_horizon, log_regime in evaluated:
            agent_keys = keyed_by_agent.setdefault(agent, {})
            for level_key in (
                (None, log_horizon, log_regime),
                (None, log_horizon, None),
                (None, None, None),
            ):
                agent_keys.setdefault(level_key, []).append((correct, timestamp))

        settings = get_settings()
        target_horizon = horizon_periods if horizon_periods is not None else _HORIZON_PERIODS
        return {
            agent: compute_hierarchical_reliability_pct(
                keyed_results,
                (symbol, target_horizon, regime),
                reference_time,
                settings.reliability_recency_half_life_days,
                settings.reliability_shrinkage_pseudo_count,
                settings.reliability_hierarchical_min_effective_sample,
            )
            for agent, keyed_results in keyed_by_agent.items()
        }
