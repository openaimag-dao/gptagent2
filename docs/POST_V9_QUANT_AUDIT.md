# POST-V9 Quantitative Validation — Final Audit (Phase 20)

**Scope:** the closing deliverable of the 20-phase POST-V9 Quantitative
Validation program, built on top of `4830f1c` ("Forecast & Alert
Intelligence V9"). This document records what each of the 12 increments in
this program actually shipped, with real before/after evidence — no
simulated numbers. Every test count below was measured by checking out the
exact commit and running `pytest --collect-only`, not estimated from memory.

**Baseline:** `4830f1c` (pre-POST-V9) — **1296 tests**.
**Final:** `461314c` (Increment 12, current tip) — **1460 tests**.
**Net:** +164 tests across 12 increments, zero regressions at any step
(every increment's own commit was preceded by a full `pytest -q` pass on
that commit's diff, and the full suite passes today: `1460 passed`).

Governing rule applied throughout: extend an existing engine/table/API/
Telegram command, never create a parallel one. Every increment below
reused at least one function, column, or module that already existed
before it started.

---

## Increment-by-increment BEFORE/AFTER

### Increment 1 (Phases 3, 8, 12, 13) — `c85055d`
**Tests:** 1296 → 1340 (+44)
**Engines touched:** `PredictionQualityEngine` (calibration sample-sufficiency),
`NoTradeEngine` (real `calibration_gap_pct` + expected-edge instead of
placeholder gates), `DataQualityEngine` → `ConvictionEngine` link, forecast
timestamp/horizon integrity.
**New migrations:** none (all fields derived from already-stored data).
**New API/Telegram fields:** NO_TRADE payload gained real `calibration_gap_pct`
and `expected_edge_pct` instead of a hardcoded threshold check.
**Also produced:** `docs/POST_V9_ARCHITECTURE_AUDIT.md` (Phase 1 — the
full dependency-map audit that grounded every subsequent increment in
file:line evidence of the real, current code rather than assumption).

### Increment 2 (Phases 10, 11) — `1433ee2`
**Tests:** 1340 → 1348 (+8)
**Engine touched:** `AlertPerformanceEngine` — "Alert Performance 2.0."
**New migration:** `0033_alert_performance_excursions.py` — adds
max-favorable/max-adverse excursion + edge-vs-baseline columns to
`AlertPerformanceGrade` (extends the existing table from V9 Increment 9,
not a new one).
**New Telegram fields:** excursion and edge-vs-baseline surfaced in the
existing alert-performance formatter.

### Increment 3 (Phase 5) — `d3b797e`
**Tests:** 1348 → 1359 (+11)
**Engine touched:** `AgentReliabilityEngine` — hierarchical fallback ladder
(symbol+horizon+regime → horizon+regime → global) instead of one flat
accuracy number, plus `regime_at_prediction` captured at `.log()` time.
**New migration:** `0034_agent_prediction_regime.py`.
**Bug found and fixed in this increment:** the fallback ladder mislabeled
the "horizon+regime" tier as "symbol+horizon+regime" whenever `symbol` was
`None` (which it always was in practice) — both tiers collapsed to the
same dict key. Fixed by gating the symbol-specific tier on `symbol is not
None`.

### Increment 4 (Phase 6) — `ebf7a3e`
**Tests:** 1359 → 1372 (+13)
**Engine touched:** `AgentReliabilityEngine` — `compute_agent_vote_correlation`
and `compute_redundancy_penalty_pct`, so agents that vote near-identically
no longer count as independent evidence.
**New migration:** none (pure functions over already-logged votes).

### Increment 5 (Phase 7) — `6b33f1d`
**Tests:** 1372 → 1384 (+12)
**Engine touched:** `ConsensusEngine` — redundancy-penalty application and
a max-single-agent-weight cap, both wired through `compute_consensus()` as
optional/backward-compatible params.
**Bug found and fixed in this increment:** `_apply_max_weight_cap` computed
`capped_weight = sum_others * ratio`, which is 0 when there is only one
reporting agent (nothing to redistribute from) — silently zeroing the sole
voter's influence. Fixed with a `len(weights) < 2` guard.

### Increment 6 (Phase 4) — `a9232cb`
**Tests:** 1384 → 1397 (+13)
**Engines touched:** `ProbabilityEngine` (`compute_quantile_coverage`,
`compute_quantile_coverage_by_group`), `PredictionQualityEngine` (wired
coverage into `evaluate()`).
**New Telegram fields:** p10–p90 coverage rate shown per reference-regime
and per-horizon group.

### Increment 7 (Phase 9) — `ea63cc2`
**Tests:** 1397 → 1417 (+20)
**Engine touched:** `TradeSetupEngine` — `simulate_trade_outcome` (bar-by-bar
walk-forward "first touch wins" simulation), `backtest_trade_setup_rule`,
`compute_trade_setup_expectancy`.
**New API/Telegram fields:** `trade_economics` (win rate, expectancy,
sample size) attached to every trade setup.

### Increment 8 (Phase 17) — `1183464`
**Tests:** 1417 → 1427 (+10)
**Engine touched:** `ForecastEngine` — `ForecastStatus` lifecycle enum
(ACTIVE/INVALIDATED/SUPERSEDED/GRADED) with two pure transition functions
sharing one invariant: only a still-ACTIVE row transitions; a row already
carrying a terminal marker keeps it.
**New migration:** none — `forecast_status` was already `String(20)`, so
the new enum values are Python-side only.

### Increment 9 (Phase 15) — `00e7bcc`
**Tests:** 1427 → 1440 (+13)
**New module:** `app/services/common/statistics.py` — `compute_wilson_interval`
(small-sample binomial proportion CI) and `compute_bootstrap_ci`
(percentile bootstrap for means). Confirmed via repo-wide search this
statistical-significance capability did not exist anywhere before this
increment.
**Wired into:** `PredictionQualityEngine`, `SelfLearningEngine`,
`AlertPerformanceEngine`, `TradeSetupEngine` — every place already
reporting a raw accuracy/win-rate percentage now also reports its
confidence interval and sample size next to it.

### Increment 10 (Phase 14) — `9188e52`
**Tests:** 1440 → 1454 (+14)
**Engines touched:** `ForecastEngine` (`grade_momentum_baseline`,
`compute_historical_mean_baseline_error_pct`), `AccuracyEngine`
(`beats_random_walk`, `beats_momentum_baseline`, `beats_historical_mean_baseline`).
**New migration:** `0035_forecast_baseline_comparison.py` — two nullable
columns on `price_forecast_snapshots`, filled in by the same
`grade_price_forecasts()` call using data it already fetches (zero extra
I/O).
**Why this matters:** a forecast that is merely non-random (>50% direction
accuracy) is not the same claim as a forecast that beats doing nothing
clever. All three `beats_*` fields are honestly `None`, never a fabricated
`True`/`False`, whenever either side of the comparison lacks graded data.

### Increment 11 (Phase 16) — `34530a0`
**Tests:** 1454 → 1457 (+3)
**Engine touched:** `AccuracyEngine` — `summarize_by_regime_horizon`, a
2D regime×horizon accuracy matrix. Confirmed via research that every
existing accuracy breakdown (`bucket_accuracy`, `summarize_by_asset`,
`compute_quantile_coverage_by_group`) only ever groups on one dimension at
a time; no combined key existed anywhere.
**New migration:** none — reuses `regime_at_forecast` (added in V9) and
`horizon`, both already persisted on every row.
**New dashboard field:** "Regime × Horizon Accuracy" table on the
Prediction Accuracy page.

### Increment 12 (Phase 19) — `461314c`
**Tests:** 1457 → 1460 (+3)
**Module touched:** `app/scheduler/jobs.py` — `_timed()`, a single wrapper
applied once at job registration (not copy-pasted into all 30 job bodies)
that logs each job's real wall-clock duration via `time.monotonic()` — the
same convention `WatchdogEngine.run_cycle()` already used. Confirmed via
research that only Watchdog and provider-health had any timing
instrumentation before this increment; every other job (forecast compute/
grade/invalidate, alert checks, scanner, correlations, regime, signals,
reports, ...) logged only counts, never duration.
**New migration:** none.

---

## Phase 18 audit: on-chain/derivatives honesty (no code changed)

Researched and confirmed already correct — no code change needed:

- `OnChainIntelligenceEngine.get_snapshot` (`app/services/onchain/engine.py:79-95`)
  initializes every metric to `None`, computes `available` as "any real
  metric present," and `_reason()` (lines 119-142) explicitly states which
  metrics need an unconfigured API key rather than inventing values.
- `WhaleIntelligenceEngine.get_snapshot` (`app/services/whales/engine.py:79-124`)
  returns `{"available": False, "reason": ..., "would_return": [...]}` on
  total data failure instead of fabricated numbers.

This is the "what I did not change because it was already correct" case
for Phase 18: both engines already followed the "honest `None` over
fabricated data" convention this entire program enforces everywhere else.

---

## What this program did not attempt

- **Per-symbol/per-horizon agent reliability** and **true walk-forward
  parameter optimization** — both were explicitly deferred in the original
  V9 spec as separate, larger-scope projects, and remain deferred here;
  nothing in POST-V9 touched them.
- **BNB/XRP/DOGE historical backtest coverage** — the historical OHLCV
  pipeline (`app/services/history/registry.py`) still hardcodes BTC/ETH/SOL
  only; extending it is additive but adds ongoing free-tier API load, and
  was never in scope for this validation program.

---

## Summary

12 increments, 1296 → 1460 tests (+164, zero regressions at any step), 3
new migrations (`0033`, `0034`, `0035`), one new module
(`app/services/common/statistics.py`), one architecture audit doc, one bug
found and fixed in agent-reliability tier collapsing, one bug found and
fixed in single-agent weight-cap zeroing. Every increment extended an
existing engine, table, or module — no ForecastEngine2, no
CalibrationEngine2, no parallel alert system. Phase 18 was audited and
found already honest; it required no change.
