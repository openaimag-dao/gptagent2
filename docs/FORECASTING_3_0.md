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

This report was written after PR #140 merged, with every number pulled
live from a running instance against the local Postgres database (not
estimated or fabricated) — see each section below for exactly how.

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
- **Rolling performance windows (7D/30D/90D)** on the official-forecast
  API — the underlying `since` filter existed (built for the Telegram
  weekly digest) but was never exposed via the dashboard/API.
- **Per-job execution tracking and DB-derived operational health** on
  `/api/status` — jobs ran but had no `last_run_at`/`last_success_at`/
  `last_failure_at` visibility, and there was no single place to see
  `grading_pending_count`/`stale_forecast_count`.
- **Telegram `/forecast SYMBOL`** — no command existed to check an
  official call plus its own track record from Telegram.
- **Error Lab → Forecast Detail click-through** — Error Lab listed wrong
  calls but didn't link to their full detail page.
- **Historical replay / no-leakage validation** — the leakage-safe design
  was already followed by convention in every baseline function's own
  docstring, but nothing *proved* it; a bug could have shipped silently.

## WHAT WAS CHANGED

Ten increments, each its own PR, each independently tested and live-
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

Every increment that touched `price_forecast_snapshots` used an additive,
nullable-by-default migration — no backfill, no data rewrite, honest
`None` for rows that predate a column. Migrations `0040`-`0043` (this
window): `zero_return_baseline_error_pct`, `regime_mean_baseline_error_pct`,
`calibrated_confidence_pct`+`data_quality_score`,
`p10_pct..p90_pct`+`crps_pct`.

**Explicitly not done, on purpose:** no new engine, no new AI agent, no
change to the production forecast math (`ForecastEngine.compute()`'s
actual target/direction/probability formula is untouched by this entire
program) — every increment only extended grading, measurement, and
display around the existing forecast.

## TEST RESULTS

**1622 → 1636 → 1668 passed**, zero failures at every step (numbers pulled
from each PR's own recorded test plan, not estimated): 1622 immediately
before increment 1 (PR #131's own baseline), 1636 after increment 4 (PR
#134), **1668 verified live just now** via `pytest -q` against this
branch at `origin/main` tip after PR #140. `ruff check` and
`ruff format --check` clean on every file touched across all ten
increments. Every increment independently ran the full suite before and
after its own change and before merge — no increment shipped with a red
suite, and no increment's new tests were later found broken by a
subsequent increment.

## FORECAST COVERAGE BY ASSET

Pulled live via a direct query against `price_forecast_snapshots` (official
rows only, `is_official_daily = true`) on this environment's database:

| Asset | Official rows | First date | Last date |
|---|---|---|---|
| BTC | 5 | 2026-08-12 | 2026-08-23 |
| SOL | 4 | 2026-08-16 | 2026-08-23 |
| LINK | 3 | 2026-08-19 | 2026-08-23 |
| UNI | 3 | 2026-08-21 | 2026-08-23 |

All four official symbols have at least one official forecast; coverage is
still shallow (3-5 days each) because this is a development/sandbox
database, not a long-running production deployment — sample sizes below
are correspondingly small and flagged as such throughout.

## GRADING COVERAGE BY ASSET

Same live query, distinguishing **evaluated** (horizon has elapsed,
`evaluated_at` set — includes Neutral calls) from **direction-graded**
(`direction_correct` resolvable — excludes Neutral calls, which honestly
have no direction to grade):

| Asset | Evaluated | Direction-graded | Neutral (excluded from direction grading) |
|---|---|---|---|
| BTC | 4 / 5 | 4 | 0 |
| SOL | 4 / 4 | 4 | 0 |
| LINK | 3 / 3 | 3 | 0 |
| UNI | 3 / 3 | 2 | 1 |
| **Total** | **14 / 15** | **13** | **1** |

The one still-ungraded row (BTC) has not yet had its 24h horizon elapse
in stored history at the time this report was generated.

## WIN RATE BY ASSET

Pulled live from `GET /api/forecast/official/performance?window=all`
(Wilson 95% CI shown — every sample here is small, so treat the point
estimate with real caution, exactly as the CI communicates):

| Asset | Graded | Direction accuracy | 95% CI | Avg \|error\| | RMSE | Target reached |
|---|---|---|---|---|---|---|
| BTC | 4 | 75.0% | 30.1-95.4% | 1.40% | 1.73% | 75.0% |
| SOL | 4 | 75.0% | 30.1-95.4% | 1.22% | 1.40% | 25.0% |
| LINK | 3 | 33.3% | 6.2-79.2% | 1.28% | 1.70% | 66.7% |
| UNI | 2 | 100.0% | 34.2-100% | 0.85% | 0.89% | 50.0% |
| **Overall** | **13** | **69.2%** | **42.4-87.3%** | **1.23%** | **1.52%** | **53.9%** |

## WIN RATE BY HORIZON

The official daily job computes **only the 24h horizon** — confirmed by
reading `generate_official_daily_forecast_job`'s own call site
(`compute(symbol, "24h", is_official_daily=True)`, no loop over other
horizons). `HORIZONS` (`24h`/`3d`/`7d`/`30d`) exists and is used by the
intraday/live `GET /api/forecast/{symbol}?horizon=` endpoint, but 3d/7d/30d
are never persisted as official rows — so there is honestly nothing to
report at those horizons for the official surface, and no artificial rows
were added to make this table look more populated than it is. All 13
direction-graded official rows above are 24h.

## WIN RATE BY REGIME

Pulled live from the same `official/performance` endpoint's
`regime_breakdown` (via `derive_regime_performance_breakdown`, which gates
on `agent_performance_min_sample_size`):

| Regime | Sample size | Accuracy | Status |
|---|---|---|---|
| accumulation | 8 | — | INSUFFICIENT SAMPLE |
| neutral | 2 | — | INSUFFICIENT SAMPLE |
| risk_off | 3 | — | INSUFFICIENT SAMPLE |

Every regime bucket in this environment is below the configured minimum
sample size, so accuracy is honestly withheld rather than shown from too
few data points — this is the gating working as designed, not a bug. (The
separate Prediction Accuracy pipeline's `by_regime_horizon` view, over a
larger 32-row sample that includes non-official intraday grades, does show
one regime/horizon cell — `neutral`/`24h`, n=14 — crossing its own
sufficiency threshold: 50.0% direction accuracy there.)

## CALIBRATION

Pulled live from `official/performance`'s `calibration` curve
(`derive_official_calibration_curve`, bucketed by stated `probability_pct`):

| Stated probability bucket | Count | Avg stated | Observed accuracy | Gap | Sufficiency |
|---|---|---|---|---|---|
| 40-60% | 3 | 55.0% | 0.0% | +55.0% | INSUFFICIENT |
| 60-80% | 10 | 65.2% | 90.0% | -24.8% | INSUFFICIENT |

Both buckets are marked `INSUFFICIENT` by `classify_calibration_reliability`
at this sample size — the dashboard and this report both surface that
label rather than asserting either bucket is "well calibrated" or "poorly
calibrated." The 40-60% bucket's 0% observed accuracy on n=3 is a
striking-looking number that would be irresponsible to generalize from;
it needs materially more graded history before any calibration claim is
defensible.

## BASELINE EDGE

Pulled live from `/api/accuracy`'s overall summary (32 graded rows across
both official and non-official intraday forecasts — this is the
Prediction Accuracy pipeline, a deliberately separate, larger-sample view
from the official-only scorecard above):

| Baseline | Forecast's own accuracy/error | Baseline's accuracy/error | Beats baseline? |
|---|---|---|---|
| Random walk (50% constant) | 56.25% direction accuracy | 50% | **Yes** |
| Momentum ("last move continues") | 56.25% | 38.1% | **Yes** |
| Historical mean (unconditional) | 1.0503% avg abs error | 0.3615% | **No** |
| Zero return ("assume no change") | 1.0503% | 0.2214% | **No** |
| Regime mean (conditioned on regime) | — | — (no data) | Not evaluable in this environment |

Read honestly: the forecast beats the two *directional* baselines (random
walk, momentum) but currently has a **larger point-forecast error** than
either the historical-mean or zero-return naive baselines at this sample
size. This is exactly the kind of finding the 5-baseline challenge exists
to surface rather than hide — a forecast can be directionally useful while
still not (yet, at n=32) beating "predict no change" on raw magnitude. The
regime-mean baseline is not evaluable in this sandbox: `reconstruct_regime_at`
needs at least 4 of 7 macro/equity history tables (`SPX/VIX/DXY/GOLD/
US10Y/FEDRATE`), all of which are empty here because `yfinance` calls fail
in this network environment (see README's own "Known operational
limitation: Yahoo Finance" section — a pre-existing, already-documented
constraint, not something this program introduced). The code path itself
is unit-tested with real synthetic data and confirmed correct
independent of this environment's data availability.

## REMAINING LIMITATIONS

Honestly out of scope for this program, in the order the original spec
raised them:

- **Champion/challenger shadow-mode comparison** and **forecast
  distribution model comparison (Model A/B/C/D)** — deliberately not
  started. The spec's own governing principle is explicit: "First make the
  current system consistent/auditable/measurable/self-evaluating; only
  after proven OOS improvement is changing production forecasting math
  allowed." This program built the measurement infrastructure (baselines,
  CRPS, calibration, leakage validation) that a future champion/challenger
  effort would need to make that comparison honestly — but with only
  13-32 graded rows currently in this environment, there is not yet enough
  out-of-sample history to run a statistically meaningful A/B/C/D
  comparison. Starting it now would risk exactly the "small-sample
  overclaiming" this whole program was built to prevent.
- **Regime-mean baseline data availability** — the code is correct and
  tested (see BASELINE EDGE above), but is starved of real data in this
  sandbox by the pre-existing Yahoo Finance limitation. This will resolve
  itself once run somewhere with real yfinance access, no code change
  needed.
- **Sample sizes throughout** — every table in this report is small (2-32
  rows). Every number above is reported honestly with its real sample
  size and, where the codebase's own gating says so, marked
  `INSUFFICIENT SAMPLE` rather than a bare percentage. This will improve
  automatically as the official daily job keeps running; no code change is
  needed to "unlock" more history, only time.
- **3d/7d/30d official horizons** — currently 24h-only for the official
  surface, by original design, not an oversight of this program (see WIN
  RATE BY HORIZON above).
- **Error taxonomy** stays at the existing 3-way
  (`TIMING_ERROR`/`VOLATILITY_ERROR`/`DIRECTION_ERROR`) rather than the
  spec's fuller list — this was a deliberate prior design choice (this
  table has no causal evidence to support finer classes without inventing
  one) and this program did not revisit it.
