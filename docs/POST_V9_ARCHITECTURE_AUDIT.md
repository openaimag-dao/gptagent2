# POST-V9 Architecture Audit — Dependency Map

**Scope:** Phase 1 of the POST-V9 Quantitative Validation program. This document
traces the actual, current (post-merge `4830f1c`, "Forecast & Alert Intelligence
V9") data flow for every decision-relevant engine — not a design intent, the
real code as read on this date. No code was changed to produce this document;
every claim below is backed by a file:line reference.

**Method:** every engine below was re-read from the current `main` before this
document was written. Where a claim implies a gap or inconsistency, the exact
lines proving it are cited.

---

## 1. ProbabilityEngine

| | |
|---|---|
| **Inputs** | `rsi_series`, `returns_series` (from synced OHLCV history), optional `regime_series`/`reference_regime` (from a caller-provided `regime_index`) |
| **Source table** | `CryptoHistory` / `EquityHistory` / etc. (per-symbol, resolved via `find_symbol_config`) |
| **Timestamp** | `rows[-1].timestamp` — the latest synced candle for the symbol/timeframe at call time (`app/services/probability/engine.py:204`) |
| **Horizon** | `horizon` param, periods on the DAILY timeframe (1/3/7/30 for 24h/3d/7d/30d) |
| **Calculation** | `compute_rsi_probability`: buckets historical RSI within ±5 of the reference RSI, optionally further restricted to same-regime periods (fallback to RSI-only if the regime-matched sample is `< _MIN_SAMPLE_SIZE=8`), then computes up/down/flat frequency + quantiles over `compute_forward_returns` (compounded, not naive-indexed) |
| **Output** | `ProbabilitySnapshot` fields: `prob_up_pct`, `prob_down_pct`, `prob_flat_pct`, `avg_forward_return_pct`, `p10_pct`…`p90_pct`, `regime_conditioned`, `reference_regime`, `sample_size` |
| **Persistence** | `ProbabilitySnapshot` row, **always INSERTed** (append-only, one row per `compute_and_store` call) — `app/services/probability/engine.py:199-210` |
| **Consumer** | `ForecastEngine.compute()` (below); `ConvictionEngine.evaluate_probability` (folds in Brier score separately); `/api/probability` |

**Verified correct:** `compute_forward_returns` compounds every intermediate
period rather than naively indexing `returns[i+horizon]` (this was a real bug
fixed pre-V9, confirmed still fixed: `app/services/probability/engine.py:24-47`).
Regime-conditioning honestly reports `regime_conditioned=False` on fallback
rather than claiming conditioning it didn't have data for.

---

## 2. RegimeDetector / MarketRegime

| | |
|---|---|
| **Inputs** | Cross-asset signals (BTC dominance, DXY, yields, VIX, etc.) via `_CORE_REGIME_INPUTS` |
| **Source table** | Multiple `AssetPrice`/history tables, read fresh each cycle |
| **Timestamp** | Latest synced row per input at detection time |
| **Horizon** | N/A — point-in-time classification, not a forward-looking horizon |
| **Calculation** | Rule cascade over the core inputs → one of 5 `MarketRegime` values (or `NEUTRAL` on disagreement); `compute_regime_confidence` scores 0-100 by what fraction of `_CORE_REGIME_INPUTS` were actually non-`None` on the deciding snapshot (`app/services/analysis/regime.py:263-283`) |
| **Output** | `regime` (str), `confidence_pct` (int, `NEUTRAL` always LOW) |
| **Persistence** | `MarketRegimeSnapshot` row (latest read via `.order_by(computed_at.desc()).limit(1)`) |
| **Consumer** | `ProbabilityEngine` (via `regime_index`/`reconstruct_regime_at`, historical reconstruction — see below), `SimilarMarketEngine`, `ForecastEngine` (`regime_label`, `regime_at_forecast`), NO_TRADE (`latest_regime_confidence_pct`) |

**Two distinct "regime" reads exist and must not be confused:**
1. `RegimeDetector.get_latest()` — the CURRENT live regime, used directly by
   NO_TRADE's `check_regime_uncertainty` and Forecast's `regime_at_forecast`.
2. `build_regime_index()` / `reconstruct_regime_at()` — a **historical**
   reconstruction of what regime was active at any past timestamp, used only
   by `ProbabilityEngine`'s regime-conditioning and `SimilarMarketEngine`'s
   analogue filtering. These share one implementation
   (`app/services/analysis/regime.py`, consolidated in V9 Increment 1 —
   confirmed no duplicate exists in `similar_market/engine.py` anymore).

These are two different things measuring "regime" at two different moments
and must never be substituted for each other — verified they aren't (grep
confirms `reconstruct_regime_at` and `RegimeDetector.get_latest` are never
called interchangeably).

---

## 3. ForecastEngine

| | |
|---|---|
| **Inputs** | `ProbabilitySnapshot` (fresh, computed synchronously inside `compute()`), latest OHLCV row, `PredictionQualityEngine.evaluate()`, `TechnicalAnalysisSnapshot`, **latest `WatchdogSnapshot`** (see finding below), `ExplanationEngine`, forecast accuracy track record |
| **Source table** | `PriceForecastSnapshot` (write), `ProbabilitySnapshot` (read, freshly written this call), `WatchdogSnapshot` (read, **not** freshly computed) |
| **Timestamp** | `reference_timestamp = latest.timestamp`, pinned to the exact candle `ProbabilitySnapshot` was computed from (`app/services/forecast/engine.py:770-780` — deliberately re-fetched *after* `compute_and_store`, matched by `probability_snapshot.reference_timestamp`, to avoid a race between two `get_series()` calls) |
| **Horizon** | One of `HORIZONS = {"24h":1, "3d":3, "7d":7, "30d":30}`, passed straight through to `ProbabilityEngine` |
| **Calculation** | Price target/path/distribution: deterministic transform of `avg_forward_return_pct` + ATR (normal approximation). `probability_pct = max(prob_up_pct, prob_down_pct, prob_flat_pct)` — **the raw value, not quality-adjusted** (see Finding F-1). `conviction = classify_conviction(...)` separately produces `effective_confidence_pct` (sample-size- and Brier-discounted) |
| **Output** | Full payload: `current_price`, `target_price`, `probability_pct`, `confidence` (dict incl. `effective_confidence_pct`), `forward_return_quantiles`, `regime_conditioned`, `key_levels`, `consensus`, `forecast_version`, `forecast_status` |
| **Persistence** | `PriceForecastSnapshot`, always INSERTed with `forecast_version = MAX(version)+1` scoped to `(symbol, horizon)` — genuinely append-only, never overwritten (`app/services/forecast/engine.py:960-1003`) |
| **Consumer** | `/api/forecast/{symbol}`, `NoTradeEngine`, `TradeSetupEngine`, Scanner's `_forecast_context` hook, Telegram `/forecast` |

### Finding F-1 (confirmed, code-cited): raw probability, not calibration-adjusted, reaches the gates

`app/services/forecast/engine.py:785-793`:
```python
confidence_pct = max(
    probability_snapshot.prob_up_pct,
    probability_snapshot.prob_down_pct,
    probability_snapshot.prob_flat_pct,
)
conviction = classify_conviction(
    confidence_pct, sample_size=..., brier_score=quality["brier_score"], ...
)
```
`app/services/forecast/engine.py:913`:
```python
"probability_pct": confidence_pct,   # <-- the RAW value
```
`conviction["effective_confidence_pct"]` (the sample-size- and Brier-score-
discounted number) is used for `scenario_cases` and `track_record`, but
**`payload["probability_pct"]` — the field NO_TRADE and TradeSetup actually
read — is the uncalibrated raw number.** A symbol with a terrible historical
Brier score (near-uninformative — `quality_multiplier` near 0) can still
report `probability_pct=70%` and sail past NO_TRADE's `check_low_probability`
(default threshold 55%) untouched, even though its *calibration-adjusted*
confidence might be near 35%. See Phase 2/8 fix below.

### Finding F-2 (confirmed, code-cited): `consensus` in the Forecast payload is a stale, independently-scheduled snapshot, not a live read

`app/services/forecast/engine.py:824,875`:
```python
watchdog = await self._latest_watchdog_snapshot()
...
consensus = watchdog.consensus if watchdog is not None else None
```
`WatchdogSnapshot.consensus` is a JSON copy of `ConsensusResult.to_dict()`
taken during `WatchdogEngine.run_cycle()` — a **separate scheduled job**
(`compute_watchdog_snapshot_job`, `app/scheduler/jobs.py:700-707`) on the
same nominal interval as `compute_forecast_job` (`analysis_interval_minutes`,
default 30 min, ±5 min jitter) but **not synchronized or chained** to it.
When `ForecastEngine.compute()` is invoked on-demand (API request, or the
Scanner→Forecast hook), it always uses fresh price/probability data but can
attach a consensus reading up to one full Watchdog cycle stale (up to
~35 minutes under default config, more if that job failed or was delayed).
This consensus dict is what NO_TRADE's `check_conflicting_agents` reads
(via `consensus.get("conflict_pct")`) — **NO_TRADE's disagreement gate can
be checking agent votes from up to 35 minutes before the probability/price
data it's gating.** This is a documented, intentional design tradeoff (avoid
re-running the agent orchestrator on every forecast call — `WatchdogSnapshot`'s
own docstring: "never duplicate calculations already performed") but the
staleness bound was never quantified or surfaced. See Phase 2 recommendation.

---

## 4. ConsensusEngine

| | |
|---|---|
| **Inputs** | `AgentOrchestrator.run_all()` (5 deterministic specialist agents), optional `reliability: dict[str, float]` from `AgentReliabilityEngine.evaluate_reliability()` |
| **Source table** | None directly — agents each read their own upstream engines |
| **Timestamp** | Point-in-time, computed synchronously per call — no persistence of its own (`ConsensusEngine` docstring: "computed on demand rather than persisted") |
| **Horizon** | N/A — a vote tally, not a forward-looking read |
| **Calculation** | `compute_consensus`: per-agent weight = `max(confidence, _MIN_VOTE_WEIGHT)`, multiplied by `reliability[name]/100` when the agent has a reliability score (V9 Increment 8: Bayesian-shrunk, recency-decayed); bucketed by direction, normalized to percentages |
| **Output** | `bullish_pct`/`bearish_pct`/`neutral_pct`, `agreement_score`, `conflict_pct`, `agent_weights`, `strongest_agent` |
| **Persistence** | None of its own — only reaches disk as `WatchdogSnapshot.consensus` (a snapshot copy, see F-2) |
| **Consumer** | `CommitteeEngine.convene()` (live, same-call), `WatchdogEngine` (persisted snapshot), and — transitively, stale — `ForecastEngine`/`NoTradeEngine` via F-2 |

**Verified correct:** reliability weighting caps nothing today — an agent
with `reliability=100` still only scales its own `max(confidence, floor)`
weight; it cannot exceed its own confidence-derived weight. There is **no
minimum/maximum bound on an individual agent's total influence share** — a
single high-confidence, high-reliability agent's weight is only implicitly
bounded by the other agents' presence, not by an explicit cap. See Phase 7.

**Confirmed NOT implemented (per user's own list, verified by grep):**
inter-agent vote correlation / redundancy discounting. No code anywhere in
`app/services/consensus/` or `app/services/reliability/` computes a
pairwise vote-similarity measure. Two agents that always vote identically
are counted as two full, independent votes today.

---

## 5. CommitteeEngine

| | |
|---|---|
| **Inputs** | Same `agent_outputs` + a `ConsensusResult` — computed live, same call, via `asyncio.gather(agent_orchestrator.run_all(), reliability_engine.evaluate_reliability())` (`app/services/committee/engine.py:210-218`) |
| **Source table** | None |
| **Timestamp** | Point-in-time, same call as Consensus |
| **Horizon** | N/A |
| **Calculation** | `convene_committee`: majority direction = argmax of Consensus's own bucket percentages; dissent = `100 - majority_pct`; evidence lists built from `agent_outputs`/`consensus.agent_weights` — no re-derivation of the vote itself |
| **Output** | `CommitteeVerdict`: `majority_decision`, `dissent_pct`, `confidence_pct` (= `consensus.agreement_score`), `invalidation_risk` |
| **Persistence** | None of its own — `WatchdogSnapshot.committee_decision` stores only the decision label, not the full verdict |
| **Consumer** | `/api/committee`, Telegram `/committee`, `WatchdogSnapshot` (decision label only) |

**Verified correct:** unlike `ForecastEngine`, `CommitteeEngine.convene()`
always computes a fresh `ConsensusResult` in the same call (no stale-snapshot
risk here — F-2 is specific to `ForecastEngine`'s path through
`WatchdogSnapshot`).

---

## 6. NoTradeEngine (`app/services/trade_setup/no_trade.py`)

| | |
|---|---|
| **Inputs** | A single `ForecastEngine.compute()` payload (computed once, reused — see below) + `latest_regime_confidence_pct` (live `RegimeDetector.get_latest()`, NOT the historical reconstruction from §2) |
| **Source table** | None directly — reads other engines' outputs |
| **Timestamp** | `reference_timestamp` = the Forecast payload's own (fresh, pinned candle) |
| **Horizon** | Passed through from the caller (`evaluate_no_trade_for_symbol(..., horizon="24h")`) |
| **Calculation** | 9 independent pure checks (`check_insufficient_sample`, `check_low_probability`, `check_conflicting_agents`, `check_extreme_volatility`, `check_regime_uncertainty`, `check_poor_calibration`, `check_forecast_invalidated`, `check_stale_data`, `check_weak_historical_edge`) — ANY trigger flips to `NO_TRADE` |
| **Output** | `{"recommendation": "TRADE_OK"|"NO_TRADE", "reasons": [...]}` |
| **Persistence** | None — computed on demand, mirrors NO_TRADE's own documented design choice not to duplicate the append-only Forecast table |
| **Consumer** | `/api/no-trade/{symbol}`, Telegram `/notrade`, `TradeSetupEngine` (reuses the same verdict via `no_trade_result_from_payload`, not a second call) |

### Finding F-3 (confirmed, code-cited): `check_poor_calibration` is wired but never fed real data

`app/services/trade_setup/no_trade.py:239` (in `no_trade_result_from_payload`):
```python
result = evaluate_no_trade(
    sample_size=payload.get("sample_size"),
    probability_pct=payload.get("probability_pct"),
    dissent_pct=consensus.get("conflict_pct"),
    expected_volatility_pct=payload.get("expected_volatility_pct"),
    regime_confidence_pct=regime_confidence_pct,
    forecast_status=payload.get("forecast_status"),
    reference_timestamp=...,
    # calibration_gap_pct: NOT PASSED -- defaults to None
)
```
`check_poor_calibration(calibration_gap_pct=None, ...)` therefore **never
fires** in production — the gate exists, is unit-tested in isolation, but is
permanently dormant in the live pipeline because nothing ever computes and
passes a real `calibration_gap_pct`. This is exactly what the module's own
docstring already discloses ("calibration_gap_pct and historical_win_rate_pct
are left unevaluated here... needs real entry/stop/target levels and analog-
match win rates") but is worth stating precisely: **it is not a partial
implementation, it is 100% inert today.** See Phase 8.

### Finding F-4: no expected-edge gate — every threshold is a hard, independent cutoff

There is currently no `EXPECTED EDGE` computation (`probability × expected
move × risk/reward`) anywhere in NO_TRADE. A forecast at `probability_pct=56`
(barely above the 55% cutoff) with a tiny `expected_change_pct` and a poor
risk/reward passes `check_low_probability` cleanly even though its expected
edge is close to zero. See Phase 8.

---

## 7. TradeSetupEngine (`app/services/trade_setup/engine.py`)

| | |
|---|---|
| **Inputs** | The **same, single** `ForecastEngine.compute()` payload NO_TRADE uses (`evaluate_trade_setup_for_symbol` calls `build_forecast_engine().compute()` exactly once, then reuses it for both the NO_TRADE gate and the setup — `app/services/trade_setup/engine.py:150-165`) |
| **Source table** | None directly |
| **Timestamp** | Forecast payload's own `reference_timestamp` |
| **Horizon** | Passed through from the caller |
| **Calculation** | `direction_to_side` (Bullish/Bearish → BUY/SELL, else no side); ATR recovered from `expected_volatility_pct` (`atr = expected_volatility_pct/100 * current_price`, an inverse of how `ForecastEngine` derived that percentage in the first place — not a second ATR read); `compute_atr_levels` (reused from `PortfolioAdvisorEngine`, not duplicated) for stop/target |
| **Output** | `TradeSetup`: `side`, `entry_price`, `stop_loss_price`, `take_profit_price`, `risk_reward_ratio` (fixed 2:1, from `compute_atr_levels`'s own default), `invalidation_level`/`breakout_level` (Forecast's own `key_levels`), `reasons` (NO_TRADE's, plus `no_directional_edge` when Neutral) |
| **Persistence** | None — explicitly documented as a read-through composition, not a redundant snapshot of an already-versioned Forecast |
| **Consumer** | `/api/trade-setup/{symbol}`, Telegram `/tradesetup` |

**Verified correct:** no second forecast recompute — confirmed
`forecast_engine.compute.await_count == 1` in
`tests/test_trade_setup_engine.py`.

**Confirmed gap (expected, per spec):** no historical expectancy analysis
(win rate / average win / average loss / expectancy / profit factor / MFE /
MAE / time-to-target) exists anywhere for `TradeSetup` outputs. This is
exactly Phase 9's target.

---

## 8. Alert-producing systems (Scanner / CriticalAlertEngine / AlertEngine / AlertRuleEngine)

Four independent systems write to the shared `AlertLog` table, confirmed
unchanged in count/identity from V9:

| System | Category prefix | `data` shape | Timestamp source |
|---|---|---|---|
| Market Scanner (`scanner/engine.py`) | `scanner:*` | `{"symbols": [...], ...}` or nested `readings`/`moves` | `AlertLog.triggered_at` = `_utcnow()` at detection |
| Critical Alert System (`shocks/engine.py`) | `critical_shock:*` | `{"alert_key", "readings", "quality_score"}` (no direct `symbol`/`symbols` key at top level — resolved via `readings[0]["symbol"]`) | same |
| Smart Alert Engine (`alerts/engine.py`) | detector-specific | `detection["data"]`, varies per detector | same |
| AlertRuleEngine (`alerts/rules.py`) | user-defined | rule-specific | same |

`ScannerAlert`/`CriticalAlert` additionally track a live "episode" (for
escalation message-editing) — verified both `_edit_existing` paths correctly
edit the existing Telegram message on tier escalation rather than sending a
duplicate (confirmed in V9 Increment 10, re-verified this session).

**Cross-cutting timestamp note:** an alert's `data` never carries its OWN
reference price/timestamp explicitly — `AlertPerformanceGrade` (below)
reconstructs a reference price by finding the last daily candle at-or-before
`triggered_at`, which is a wall-clock timestamp, not a candle-aligned one.
This is a real (documented, not hidden) approximation — see §9.

---

## 9. AlertPerformanceGrade (`app/services/alert_performance/engine.py`)

| | |
|---|---|
| **Inputs** | Ungraded `AlertLog` rows; a best-effort `resolve_alert_symbol`/`resolve_alert_direction` over each row's own `data` JSON |
| **Source table** | `AlertLog` (read), daily OHLCV per resolved symbol (read), `AlertPerformanceGrade` (write, new in V9 Increment 9) |
| **Timestamp** | `reference_idx = _index_at_or_before(rows, log.triggered_at)`; `evaluated_idx = _index_at_or_after(rows, triggered_at + horizon_days)` — **candle-aligned by nearest match, not exact**, since `triggered_at` is wall-clock, not a candle timestamp (`app/services/alert_performance/engine.py:112-130`) |
| **Horizon** | `alert_grading_horizon_days` (config, default 3) — **fixed for every alert type**, not alert-type- or timeframe-aware |
| **Calculation** | `grade_alert_outcome`: `realized_move_pct` between reference and evaluated close; `significant_move` (≥ `alert_grading_significant_move_pct`, default 3.0%); `direction_continued` only when `resolve_alert_direction` found an explicit claim in `data` |
| **Output** | `significant_move` (bool), `direction_continued` (bool\|None), `realized_move_pct` |
| **Persistence** | `AlertPerformanceGrade`, one row per graded `AlertLog.id` (unique index, never re-graded) |
| **Consumer** | `/api/alert-performance(/by-type)`, Telegram `/alertperformance`, dashboard panel |

**Confirmed gap (expected, per spec):** no `max_favorable_excursion`,
`max_adverse_excursion`, `peak_move_pct`, `time_to_peak`,
`time_to_invalidation`, `post_alert_return` vs `baseline_return` (edge vs.
market), or per-alert-type breakdown of hit rate beyond the existing
`significant_move_rate_pct`/`direction_continued_rate_pct`. This is exactly
Phase 10/11's target. The single fixed 3-day horizon for every alert type
(a flash-move alert and a regime-change alert graded on the same 3-day
window) is itself a real limitation worth flagging, not just an omission.

---

## 10. AgentReliabilityEngine (`app/services/reliability/engine.py`)

| | |
|---|---|
| **Inputs** | `AgentPredictionLog` rows (one per agent per cycle it reported a direction), joined against realized BTC price moves |
| **Source table** | `AgentPredictionLog` (read/write), `CryptoHistory` (BTC only — read) |
| **Timestamp** | `reference_timestamp` = BTC's latest synced daily close at logging time; evaluation joins by exact timestamp match against stored history |
| **Horizon** | Fixed `_HORIZON_PERIODS = 1` (next daily close) — **not per-agent, per-symbol, or per-regime** |
| **Calculation** | `compute_shrunk_reliability_pct` (V9 Increment 8): per-result recency weight `0.5 ** (age_days / half_life_days)`, then Bayesian shrinkage toward a 50% prior by `pseudo_count` pseudo-observations |
| **Output** | `{agent_name: accuracy_pct}` — flat, one number per agent, no dimensionality |
| **Persistence** | `AgentPredictionLog` (append-only) |
| **Consumer** | `ConsensusEngine.compute_consensus` (weight multiplier), `CommitteeEngine` (same, via Consensus) |

**Confirmed gap (expected, per spec):** reliability is a single global number
per agent — no per-symbol, per-horizon, or per-regime breakdown, and no
hierarchical fallback. Every agent's "edge" is measured against ONE proxy
(BTC daily direction), regardless of what symbol/horizon the agent's vote is
actually being used to weight elsewhere in the system (this mismatch is
already honestly documented in the module's own docstring, carried over from
before V9). This is exactly Phase 5's target.

---

## Cross-Cutting Checks (per the audit brief)

| Check | Finding |
|---|---|
| Different market snapshots used simultaneously? | **Yes, F-2**: `ForecastEngine`'s `consensus` field is a `WatchdogSnapshot`-cycle snapshot, not synchronized with the same call's fresh price/probability data. |
| Timestamps mixed? | `AlertPerformanceGrade`'s wall-clock `triggered_at` vs. candle-aligned OHLCV timestamps is a real (bounded, ≤1 candle) approximation — not a bug, but not exact either. Everywhere else, `reference_timestamp` is a genuine candle timestamp, propagated consistently (`ProbabilityEngine` → `ForecastEngine` → `NoTradeEngine`/`TradeSetupEngine`). |
| Horizons mixed? | No cross-horizon mixing found in Forecast/Probability/NO_TRADE/TradeSetup — `horizon` is threaded as a single string/int through the whole chain per call. `AlertPerformanceGrade` uses one fixed horizon for every alert type (a real limitation, not a mixing bug). |
| Stale value instead of current? | **Yes, F-2** (Watchdog-cycle consensus in Forecast). `RegimeDetector.get_latest()` used by NO_TRADE is likewise the last-computed regime snapshot (same cadence as Forecast, `analysis_interval_minutes`) rather than a synchronous recompute — same class of staleness, smaller magnitude since Forecast/regime jobs share a schedule more directly than Forecast/Watchdog do. |
| Same metric recomputed by multiple engines? | Not found. `ForecastEngine` computes probability once (via `ProbabilityEngine.compute_and_store`) and reuses it; `NoTradeEngine`/`TradeSetupEngine` share one Forecast call; `CommitteeEngine` computes Consensus fresh once per call, no duplicate. |
| Hidden fallback? | `compute_rsi_probability`'s regime→RSI-only fallback is explicit and flagged (`regime_conditioned=False`). No other silent fallback found in the traced chain. |
| Silent missing-data substitution? | **Yes, indirectly**: `DataQualityEngine.assess_all()` exists and correctly reports `status: "empty"` for symbols with zero rows, but **is never consumed by any decision engine** (`ForecastEngine`, `ConsensusEngine`, `ConvictionEngine`, `NoTradeEngine`, `CommitteeEngine` — grep-confirmed zero references). A degraded/missing data quality signal exists but does not currently lower confidence, gate NO_TRADE, or appear anywhere in a decision path. This is Phase 12's target. |

---

## Roadmap: what this audit found vs. what's already correct

**Already correct, verified, not to be touched (per the anti-duplication rule):**
- `compute_forward_returns` compounding (no lookahead)
- Append-only `PriceForecastSnapshot` versioning + `_persist`'s `MAX(version)+1` scoping
- `NoTradeEngine`/`TradeSetupEngine`'s single-shared-forecast-call design
- Backtest engine's `fill_lag_periods=1` (execution lag), `fee_pct`/`slippage_pct` (V9-era, pre-existing)
- Escalation message-editing (Scanner + CriticalAlertEngine)
- Regime-reconstruction consolidation (`build_regime_index`/`reconstruct_regime_at`, one implementation)
- Agent-reliability shrinkage + recency decay (V9 Increment 8)

**Real, concrete gaps found (feed Phases 2-20 below):**
- F-1: `probability_pct` reaching NO_TRADE/TradeSetup is raw, not calibration-adjusted
- F-2: Forecast's `consensus` field can be up to ~35 min stale relative to its own price/probability read
- F-3: `check_poor_calibration` is wired but permanently inert (never fed data)
- F-4: no expected-edge gate in NO_TRADE
- DataQualityEngine fully disconnected from every decision path
- No inter-agent correlation/redundancy discounting (confirmed absent, as README already discloses)
- No hierarchical (symbol/horizon/regime) agent reliability
- No historical expectancy analysis for TradeSetup outputs
- `AlertPerformanceGrade` has no MFE/MAE/peak/edge-vs-baseline, and uses one fixed horizon for every alert type
- No statistical-significance (sample size / confidence interval) reporting anywhere in the accuracy/calibration/quantile output

This document is the input to Phases 2-20. Implementation proceeds in
increments, each extending an existing engine (never a `*Engine2`), tested,
and reported honestly against what was and wasn't tractable in this pass.
