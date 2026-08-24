# Forecasting 3.0 — Closing Report

**Scope:** the "make the current forecasting system consistent, auditable,
multi-asset, statistically measurable, and self-evaluating" program
requested for the existing Forecasting 2.0 surface (official daily
forecasts, automatic grading, Prediction Accuracy dashboard). Governing
rule applied throughout, per the original instruction: **extend an
existing engine/table/API/Telegram surface, never create a parallel one.**
No new AI agents were created in this program. Every increment below
reused at least one function, column, table, or module that already
existed before it started — confirmed in each PR's own description with
file:line references to the code being extended.

This report was written after PR #143 merged, with every number pulled
live from a running instance against the local Postgres database (not
estimated or fabricated) — see each section below for exactly how. It was
first published after PR #140 (ten increments) and updated in place after
PR #143 (twelve) once two more real, spec-named gaps were found on
re-audit; see the note at the end of WHAT WAS CHANGED for what changed
between those two versions.

---

## WHAT ALREADY EXISTED

Confirmed present and working before this program started (Forecasting
2.0 and earlier POST-V9 work):

- **Official daily forecast**: one frozen 24h call per asset per UTC day
  (`generate_official_daily_forecast_job`, `is_official_daily` +
  `official_forecast_date` with a partial unique DB index enforcing
  at-most-one-per-day), for `BTC/SOL/LINK/UNI` (`official_forecast_symbols`
  setting).
- **Automatic grading**: `grade_price_forecasts()` fills in
  `realized_price`/`error_pct`/`direction_correct`/`confidence_correct`/
  `target_reached`/`max_favorable_excursion_pct`/`max_adverse_excursion_pct`/
  `error_type` once a forecast's horizon has genuinely elapsed in stored
  history — never guessed from wall-clock time.
- **Prediction Accuracy dashboard** (`/api/accuracy`, `_aggregate_stats`):
  Daily/Weekly/Monthly/Asset/Regime×Horizon views, already reporting two
  naive-baseline comparisons (`momentum_baseline_correct`,
  `historical_mean_baseline_error_pct`) with explicit `beats_*` booleans.
- **Forecast win rate, baseline comparison, calibration fields**: Wilson
  interval / bootstrap CI helpers already existed in
  `app.services.common.statistics`, used by Quality Lab, Learning Center,
  `trade_setup`, and `alert_performance` — just not yet by the official-
  forecast pipeline (this was the first gap this program closed).
- **Regime × horizon matrix, Bull/Base/Bear, prediction range, 11-agent
  consensus, AI explanation**: all shipped prior to this program.
- **Immutable, append-only design**: `price_forecast_snapshots` was
  already INSERT-only (a new row per compute, never UPDATE-in-place, with
  `forecast_version` making lineage explicit).
- **Crypto daily history sync, stale Forecast Center root-cause fix**:
  both already shipped.
- **NO_TRADE / stale-data confidence discount**: `NoTradeEngine`
  (`app/services/trade_setup/no_trade.py`) already exists as a separate,
  mature gate; forecast confidence was already discounted for stale/poor
  data via `data_quality_score` feeding `classify_conviction()`'s
  `effective_confidence_pct`, and LIVE/RECENT/DELAYED/STALE freshness
  badges already existed on every official card. This program persisted
  and surfaced that existing discount (see increment 8) rather than
  building a second gate.

## WHAT WAS MISSING

Confirmed genuinely absent by direct code search (not by memory) before
this program:

- Statistical rigor (Wilson CI, sample-size gating) applied to the
  **official-forecast** pipeline specifically — it existed elsewhere but
  the official scorecard pooled every symbol with no per-asset breakdown
  and no confidence intervals.
- **RMSE** — searched the entire `app/services` tree; did not exist
  anywhere. Only MAE (`avg_abs_error_pct`) existed.
- **Zero-return and regime-mean baselines** — only momentum and
  historical-mean existed; 3 of the spec's 5-baseline challenge were
  missing (random walk is implicit via `beats_random_walk`'s 50% constant,
  so it never needed a column).
- **CRPS** — did not exist anywhere; only point-forecast error metrics
  (MAE, and after this program, RMSE) existed.
- **`calibrated_confidence`/`data_quality` on persisted forecast rows** —
  both were already *computed* every cycle by `classify_conviction()`
  (`effective_confidence_pct`) and `compute_data_quality_score()`, and
  already returned in the live `compute()` payload, but never *persisted*
  — an official row lost them the moment it was written.
- **Empirical quantile coverage validation** — CRPS and the probability-
  calibration curve both existed (the latter only after this program's
  own increment 1) but neither answers "is the persisted P10-P90 band's
  own WIDTH honest" — a third, distinct calibration question the original
  spec named explicitly and that stayed unanswered until increment 12.
- **Rolling performance windows (7D/30D/90D)** on the official-forecast
  API — the underlying `since` filter existed (built for the Telegram
  weekly digest) but was never exposed via the dashboard/API.
- **Per-job execution tracking and DB-derived operational health** on
  `/api/status` — jobs ran but had no `last_run_at`/`last_success_at`/
  `last_failure_at` visibility, and there was no single place to see
  `grading_pending_count`/`stale_forecast_count`.
- **Telegram `/forecast SYMBOL`** — no command existed to check an
  official call plus its own track record from Telegram.
- **Error Lab → Forecast Detail click-through**, and **prediction ID /
  CRPS / P10-P90 visibility on the daily cards and Detail page** — Error
  Lab listed wrong calls but didn't link to their full detail page; and
  after increments 8-9 added `crps_pct`/quantiles to the API, neither was
  actually rendered anywhere until increment 11 caught it on re-audit.
- **Historical replay / no-leakage validation** — the leakage-safe design
  was already followed by convention in every baseline function's own
  docstring, but nothing *proved* it; a bug could have shipped silently.

## WHAT WAS CHANGED

Twelve increments, each its own PR, each independently tested and live-
verified against a real local Postgres/Redis instance before merge (no
speculative "should work" claims — every increment includes a live
verification note in its own PR description):

| # | PR | What shipped |
|---|-----|---|
| 1 | #131 | Per-symbol performance breakdown, rolling `since` window exposed via API, pagination/date-range on official history |
| 2 | #132 | Per-job execution tracking (`_timed()` wrapper) + DB-derived operational health on `/api/status` |
| 3 | #133 | Telegram `/forecast SYMBOL` (today's call + 30-day track record) |
| 4 | #134 | Error Lab → Forecast Detail click-through |
| 5 | #135 | RMSE as a second, distinct price-accuracy metric alongside MAE |
| 6 | #136 | Zero-return baseline (3rd of 5) |
| 7 | #137 | Regime-mean baseline (4th of 5), reusing `build_regime_index`/`reconstruct_regime_at` |
| 8 | #138 | `calibrated_confidence_pct`/`data_quality_score` persisted and surfaced on official cards |
| 9 | #139 | CRPS over the persisted p10-p90 quantile distribution |
| 10 | #140 | Historical replay leakage validation (test-only, no production code changed) |
| 11 | #142 | Prediction ID + CRPS/P10-P90 visibility on daily cards and Detail page (closed a rendering gap increments 8-9 left open) |
| 12 | #143 | Empirical quantile coverage validation (P10-P90 ≈ 80%, P25-P75 ≈ 50%) |

Every increment that touched `price_forecast_snapshots` used an additive,
nullable-by-default migration — no backfill, no data rewrite, honest
`None` for rows that predate a column. Migrations `0040`-`0043`:
`zero_return_baseline_error_pct`, `regime_mean_baseline_error_pct`,
`calibrated_confidence_pct`+`data_quality_score`,
`p10_pct..p90_pct`+`crps_pct`. Increments 11-12 needed no new migration —
both were pure display/aggregation work over columns already persisted by
increment 9.

**Explicitly not done, on purpose:** no new engine, no new AI agent, no
change to the production forecast math (`ForecastEngine.compute()`'s
actual target/direction/probability formula is untouched by this entire
program) — every increment only extended grading, measurement, and
display around the existing forecast.

**Between the first and second publish of this report:** this report was
first written and published as PR #141 after ten increments, itself
presented as the closing deliverable. On the next work session, re-reading
the report's own REMAINING LIMITATIONS section against the original spec
surfaced two more concrete, safely-actionable gaps it had missed
(increments 11 and 12 above) — both low-risk, additive, and directly
enabled by infrastructure the first ten increments had already built. This
version reflects that update; the honest possibility remains that another
re-read finds a thirteenth.

## TEST RESULTS

**1622 → 1636 → 1668 → 1671 passed**, zero failures at every step (numbers
cross-checked against each PR's own recorded test plan via the GitHub API,
not estimated): 1622 immediately before increment 1 (PR #131's own
baseline), 1636 after increment 4 (PR #134), 1668 after increment 10 (PR
#140), **1671 verified live just now** via `pytest -q` against this branch
at `origin/main` tip after PR #143. `ruff check` and `ruff format --check`
clean on every file touched across all twelve increments. Every increment
independently ran the full suite before and after its own change and
before merge — no increment shipped with a red suite, and no increment's
new tests were later found broken by a subsequent increment.

## FORECAST COVERAGE BY ASSET

Pulled live via a direct query against `price_forecast_snapshots` (official
rows only, `is_official_daily = true`) on this environment's database:

| Asset | Official rows | First date | Last date |
|---|---|---|---|
| BTC | 6 | 2026-08-12 | 2026-08-24 |
| SOL | 5 | 2026-08-16 | 2026-08-24 |
| LINK | 4 | 2026-08-19 | 2026-08-24 |
| UNI | 4 | 2026-08-21 | 2026-08-24 |

All four official symbols have at least one official forecast; coverage is
still shallow (4-6 days each) because this is a development/sandbox
database, not a long-running production deployment — sample sizes below
are correspondingly small and flagged as such throughout. (Row counts grew
by one per asset since this report's first publish — the daily job kept
running normally between sessions, exactly as designed.)

## GRADING COVERAGE BY ASSET

Same live query, distinguishing **evaluated** (horizon has elapsed,
`evaluated_at` set — includes Neutral calls) from **direction-graded**
(`direction_correct` resolvable — excludes Neutral calls, which honestly
have no direction to grade):

| Asset | Evaluated | Direction-graded | Neutral (excluded from direction grading) |
|---|---|---|---|
| BTC | 6 / 6 | 6 | 0 |
| SOL | 5 / 5 | 5 | 0 |
| LINK | 4 / 4 | 4 | 0 |
| UNI | 4 / 4 | 2 | 2 |
| **Total** | **19 / 19** | **17** | **2** |

Every official row currently in this database has had its 24h horizon
elapse and been graded — none pending at the time this update was written
(the one BTC row still pending in the report's first publish has since
graded).

## WIN RATE BY ASSET

Pulled live from `GET /api/forecast/official/performance?window=all`
(Wilson 95% CI shown — every sample here is small, so treat the point
estimate with real caution, exactly as the CI communicates):

| Asset | Graded | Direction accuracy | 95% CI | Avg \|error\| | RMSE | Target reached |
|---|---|---|---|---|---|---|
| BTC | 6 | 66.7% | 30.0-90.3% | 1.36% | 1.60% | 50.0% |
| SOL | 5 | 60.0% | 23.1-88.2% | 1.44% | 1.62% | 20.0% |
| LINK | 4 | 50.0% | 15.0-85.0% | 1.16% | 1.53% | 75.0% |
| UNI | 2 | 100.0% | 34.2-100% | 0.85% | 0.89% | 50.0% |
| **Overall** | **17** | **64.7%** | **41.3-82.7%** | **1.28%** | **1.52%** | **47.1%** |

## WIN RATE BY HORIZON

The official daily job computes **only the 24h horizon** — confirmed by
reading `generate_official_daily_forecast_job`'s own call site
(`compute(symbol, "24h", is_official_daily=True)`, no loop over other
horizons). `HORIZONS` (`24h`/`3d`/`7d`/`30d`) exists and is used by the
intraday/live `GET /api/forecast/{symbol}?horizon=` endpoint, but 3d/7d/30d
are never persisted as official rows — so there is honestly nothing to
report at those horizons for the official surface, and no artificial rows
were added to make this table look more populated than it is. All 17
direction-graded official rows above are 24h.

## WIN RATE BY REGIME

Pulled live from the same `official/performance` endpoint's
`regime_breakdown` (via `derive_regime_performance_breakdown`, which gates
on `agent_performance_min_sample_size`):

| Regime | Sample size | Accuracy | 95% CI | Status |
|---|---|---|---|---|
| accumulation | 11 | 81.8% | 52.3-94.9% | **sufficient** |
| neutral | 3 | — | — | INSUFFICIENT SAMPLE |
| risk_off | 3 | — | — | INSUFFICIENT SAMPLE |

Unlike the report's first publish (where every regime bucket was below the
sufficiency floor), `accumulation` has now crossed it at n=11 and reports
a real 81.8% direction accuracy — still a wide 95% CI (52-95%), so this is
directional evidence, not proof, but it's the first regime-level number in
this program with enough sample to say anything at all. `neutral` and
`risk_off` remain honestly withheld.

## CALIBRATION

Pulled live from `official/performance`'s `calibration` curve
(`derive_official_calibration_curve`, bucketed by stated `probability_pct`):

| Stated probability bucket | Count | Avg stated | Observed accuracy | Gap | Sufficiency |
|---|---|---|---|---|---|
| 40-60% | 3 | 55.0% | 0.0% | +55.0% | INSUFFICIENT |
| 60-80% | 14 | 65.79% | 78.57% | -12.78% | INSUFFICIENT |

Both buckets are still marked `INSUFFICIENT` by
`classify_calibration_reliability` at this sample size. The 60-80%
bucket's gap narrowed from -24.8pp to -12.8pp as more rows graded between
this report's two versions — exactly the kind of noisy, small-sample
movement that's why the sufficiency label exists, not evidence of a real
trend on its own.

## QUANTILE COVERAGE VALIDATION

New in increment 12 — pulled live from `official/performance`'s new
`quantile_coverage` field, checking whether the realized return actually
falls inside the persisted P10-P90/P25-P75 bands about as often as each
band's own width implies it should:

| Band | Expected coverage | Sample size | Observed coverage | Gap | Sufficiency |
|---|---|---|---|---|---|
| P10-P90 | 80% | 3 | 0.0% | -80.0pp | INSUFFICIENT |
| P25-P75 | 50% | 3 | 0.0% | -50.0pp | INSUFFICIENT |

Read honestly: at n=3 this is far below the sufficiency floor and must
not be generalized — but the raw number (0% observed vs. 80%/50%
expected) is a real, striking miss worth watching as more rows qualify.
Sample size is small specifically because a row needs BOTH a resolved
direction AND persisted quantiles to count here, and quantile persistence
only started with increment 9 partway through this program — most
currently-graded official rows predate it. This will grow automatically
as the daily job keeps running past increment 9's merge; no code change
needed.

## BASELINE EDGE

Pulled live from `/api/accuracy`'s overall summary (67 graded rows across
both official and non-official intraday forecasts — this is the
Prediction Accuracy pipeline, a deliberately separate, larger-sample view
from the official-only scorecard above):

| Baseline | Forecast's own accuracy/error | Baseline's accuracy/error | Beats baseline? |
|---|---|---|---|
| Random walk (50% constant) | 65.22% direction accuracy | 50% | **Yes** |
| Momentum ("last move continues") | 65.22% | 30.36% | **Yes** |
| Historical mean (unconditional) | 1.1131% avg abs error | 0.3759% | **No** |
| Zero return ("assume no change") | 1.1131% | 0.3363% | **No** |
| Regime mean (conditioned on regime) | — | — (no data) | Not evaluable in this environment |

Read honestly: the forecast beats the two *directional* baselines (random
walk, momentum) but currently has a **larger point-forecast error** than
either the historical-mean or zero-return naive baselines at this sample
size — the same pattern as the report's first publish, and still true at
roughly double the sample (67 vs. 32 rows). This is exactly the kind of
finding the 5-baseline challenge exists to surface rather than hide — a
forecast can be directionally useful while still not (yet) beating
"predict no change" on raw magnitude. The regime-mean baseline is still
not evaluable in this sandbox: `reconstruct_regime_at` needs at least 4 of
7 macro/equity history tables (`SPX/VIX/DXY/GOLD/US10Y/FEDRATE`), all of
which are empty here because `yfinance` calls fail in this network
environment (see README's own "Known operational limitation: Yahoo
Finance" section — a pre-existing, already-documented constraint, not
something this program introduced). The code path itself is unit-tested
with real synthetic data and confirmed correct independent of this
environment's data availability.

## REMAINING LIMITATIONS

Honestly out of scope for this program, in the order the original spec
raised them:

- **Champion/challenger shadow-mode comparison** and **forecast
  distribution model comparison (Model A/B/C/D)** — deliberately not
  started. The spec's own governing principle is explicit: "First make the
  current system consistent/auditable/measurable/self-evaluating; only
  after proven OOS improvement is changing production forecasting math
  allowed." This program built the measurement infrastructure (baselines,
  CRPS, calibration, quantile coverage, leakage validation) that a future
  champion/challenger effort would need to make that comparison honestly —
  but with only 17-67 graded rows currently in this environment, there is
  not yet enough out-of-sample history to run a statistically meaningful
  A/B/C/D comparison. Starting it now would risk exactly the "small-sample
  overclaiming" this whole program was built to prevent.
- **Regime-mean baseline data availability** — the code is correct and
  tested (see BASELINE EDGE above), but is starved of real data in this
  sandbox by the pre-existing Yahoo Finance limitation. This will resolve
  itself once run somewhere with real yfinance access, no code change
  needed.
- **Sample sizes throughout** — every table in this report is small (2-67
  rows). Every number above is reported honestly with its real sample
  size and, where the codebase's own gating says so, marked
  `INSUFFICIENT SAMPLE` rather than a bare percentage. `accumulation`
  regime crossing its sufficiency floor between this report's two versions
  is a preview of how the rest of these tables will fill in over time; no
  code change is needed to "unlock" more history, only time.
- **3d/7d/30d official horizons** — currently 24h-only for the official
  surface, by original design, not an oversight of this program (see WIN
  RATE BY HORIZON above).
- **Error taxonomy** stays at the existing 3-way
  (`TIMING_ERROR`/`VOLATILITY_ERROR`/`DIRECTION_ERROR`) rather than the
  spec's fuller list — this was a deliberate prior design choice (this
  table has no causal evidence to support finer classes without inventing
  one) and this program did not revisit it.
