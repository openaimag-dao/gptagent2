# Futures Simulator

**100% demo / paper-trading.** No real money, no real Binance orders, no
withdrawals, no live trading, no Binance API keys or real exchange
credentials anywhere in this codebase. Real market data (price, candles)
from the project's existing history/realtime infrastructure drives every
fill's reference price; everything else — account balance, positions,
orders, fees, liquidation — is simulated and stored in the `futures_sim_*`
tables. See `docs/FUTURES_SIMULATOR_MATH.md` for every formula this
system uses, with derivations.

This document is a living overview, extended as each increment ships —
not a one-time closing report. It reflects the state of the code at the
time it was last updated, not a future roadmap.

## Why this exists

A training futures terminal, built to feel like Binance Futures in logic
(margin modes, leverage, order types, liquidation) without ever touching
real funds or a real exchange, so a user can practice position sizing,
leverage, and risk management against real market prices with zero
financial risk.

## What already existed (reused, not duplicated)

- **Symbol registry** (`app.services.history.registry`) — extended with 5
  new crypto symbols (BNB, XRP, DOGE, AVAX, SUI) to reach the simulator's
  full 10-symbol roster, reusing the existing CoinGecko provider.
- **Realtime price feed** (`app.services.realtime`) — the simulator's
  `get_current_price()` prefers a fresh Coinbase-sourced realtime tick,
  falling back to the latest synced daily history candle, using the exact
  same freshness classification (`classify_freshness`) the rest of the app
  already uses.
- **Admin auth** (`app.api.admin.require_admin_key`) — the only
  authentication mechanism anywhere in this single-tenant app (there is no
  user/login model). Every mutating simulator endpoint is gated by it,
  exactly like `app/api/portfolio.py` and every other mutating endpoint in
  the app.
- **Backtest performance metrics** (`app.services.backtest.metrics`) —
  identified as directly reusable for a future performance-analytics
  endpoint (Sharpe, Sortino, max drawdown, profit factor, expectancy,
  win rate) rather than a new parallel engine; not yet wired in.

## Account model

One named account per deployment (`FuturesSimAccount.name`, default
`"default"`) — the honest reading of "one user, one demo account" in an
app with no login. `GET /api/simulator/account` gets-or-creates it with an
initial `wallet_balance` of `futures_sim_initial_balance_usd` (default
$10,000). `POST /api/simulator/account/reset` marks the current account
`RESET` (never deleted — old sessions stay queryable via
`account_session_id`) and creates a fresh `ACTIVE` account with the full
initial balance.

`wallet_balance`, `realized_pnl_total`, `fees_paid_total`, and
`funding_paid_total` are the only account fields persisted incrementally.
`equity`, `unrealized_pnl`, `used_margin`, `available_margin`, and
`margin_ratio` are always derived live from open positions — see
`docs/FUTURES_SIMULATOR_MATH.md` §9.

Every account response is explicitly labeled
`"paper_trading": true, "real_funds_used": false`.

## Orders

Four order types: MARKET, LIMIT, STOP_MARKET, TAKE_PROFIT_MARKET.

- **MARKET** fills immediately against the current reference price plus
  configured slippage (§3 of the math doc).
- **LIMIT** rests (`status=NEW`) until the current price crosses `price`
  favorably (a BUY at or below, a SELL at or above), then fills at exactly
  that price — no slippage, since a guaranteed price is the entire point
  of a limit order.
- **STOP_MARKET** / **TAKE_PROFIT_MARKET** rest until the current price
  crosses `stop_price` (a BUY at or above, a SELL at or below — both order
  types trigger identically, differing only in intended use, matching
  real exchange semantics), then fill as a genuine MARKET order (with
  slippage) from that point on.

A scheduled job (`fill_futures_sim_orders_job`, same cadence as the
position monitor — every `futures_sim_position_monitor_interval_minutes`)
fills any resting order whose trigger price has been crossed, since that
can happen purely from a price move with no further action from the user.
Deterministic fill model (task's own stated preference over an unrealistic
partial-fill simulation): a resting order either fills completely or
stays `NEW` — this simulator has no order book, so there is no
`PARTIALLY_FILLED`.

- **Idempotent**: every order carries a `client_order_id`
  (client-supplied or server-generated); a duplicate id returns the
  original order unchanged (`idempotent_replay: true`) rather than
  double-executing.
- **ONE-WAY position mode**: at most one open position per
  `(account, symbol)`. An order against an existing position increases,
  reduces/closes, or "flips" it — see §5 of the math doc for the exact
  semantics, including how `reduceOnly` caps rather than flips or errors.
- **Validated**: side, quantity, margin mode, leverage (against the
  symbol's own SIMULATED bracket) are checked at placement time; a
  rejected order is still persisted with `status=REJECTED` and a
  `reject_reason`, never silently dropped. Available margin is checked at
  fill time for every order type (MARKET fills immediately, so placement
  time and fill time are the same instant for it) — a resting order does
  NOT reserve margin at placement time, so it can still be REJECTED at
  fill time if margin has become insufficient in the meantime; a
  documented simplification versus a real exchange's margin-reservation
  model.

`DELETE /api/simulator/orders/{id}` cancels a resting (`status=NEW`)
LIMIT/STOP_MARKET/TAKE_PROFIT_MARKET order. MARKET orders fill
synchronously and are never left in a cancellable resting state;
attempting to cancel one (or an already-FILLED/CANCELLED/REJECTED order)
is an honest 400, never a silent no-op.

## Positions

`GET /api/simulator/positions` (optionally `status=ALL` for closed
positions too) returns every position with live `mark_price`,
`unrealized_pnl`, and `roi_pct` computed against the current reference
price for any OPEN row.

`POST /api/simulator/positions/{id}/close` closes fully or partially, by
an explicit `quantity` or a `percent` (task: Close / 25% / 50% / 75% /
100% buttons map directly to this).

`POST /api/simulator/positions/{id}/sl-tp` sets or clears (pass `null`) a
position's stop-loss and take-profit trigger prices. Validated against the
position's side and entry price — an inverted SL/TP (e.g. a LONG's
stop-loss above entry) is rejected outright rather than silently accepted
and never triggering. **The AI forecast never sets these automatically** —
this endpoint only ever fires from an explicit user action.

## Liquidation, stop-loss, take-profit

A scheduled job (`check_futures_sim_positions_job`, every
`futures_sim_position_monitor_interval_minutes` — default 1 minute) scans
every OPEN position and auto-closes any whose current mark price has
crossed its liquidation price, stop-loss, or take-profit, in that priority
order (liquidation always wins if multiple have crossed on the same
check). See §8 and §11 of the math doc for the exact liquidation formulas
(ISOLATED and CROSS) and trigger logic. An auto-closed position produces
the exact same `FuturesSimTrade` row and ledger entries a manual close
would, with `exit_reason` set to `LIQUIDATION`, `STOP_LOSS`, or
`TAKE_PROFIT`.

## Margin modes

- **ISOLATED**: a position's own initial margin is its only cushion
  against liquidation.
- **CROSS**: the rest of the account's equity (wallet balance plus every
  other open position's unrealized PnL) adds to that cushion, computed
  live on every position mutation — never a cached or approximate number.

## Fees

Configurable maker/taker schedule (`futures_sim_maker_fee_pct` /
`futures_sim_taker_fee_pct`, never hardcoded at a call site). Every fill
records its own `fee_rate_pct` and `fee_amount` on the order row, and a
separate `FEE` ledger entry from any `REALIZED_PNL` entry — fee and PnL
amounts are never mixed into one ledger row.

## History and audit trail

- `GET /api/simulator/orders` — order history (symbol filter, limit).
- `GET /api/simulator/trades` — realized trade history (one row per
  close/reduce/liquidation/SL/TP event), with `gross_pnl`, `fees`,
  `funding`, `net_pnl`, `roi_pct`, `duration_seconds`, `exit_reason`.
- `GET /api/simulator/ledger` — the immutable, append-only balance ledger
  (`DEPOSIT` / `RESET` / `OPEN` / `FEE` / `REALIZED_PNL` / `FUNDING`),
  each row carrying the exact signed `amount` and the resulting
  `balance_after`.

## Funding

A scheduled job (`apply_futures_sim_funding_job`, every
`futures_sim_funding_interval_hours` — default every 8 hours, matching
real exchanges' own settlement cadence) charges (or pays) funding to
every OPEN position. Uses real funding-rate data from the same
`WhaleIntelligenceEngine` the Whale Intelligence page already reads
(CoinGlass primary, CoinGecko derivatives fallback) where available;
falls back to a configured rate — explicitly labeled `SIMULATED` in the
ledger entry's description — when no real source has data for that
symbol. See §13 of the math doc for the exact formula, sign convention,
and how it interacts with a trade's `funding` field at close time.

## Mark price

Position `mark_price`, unrealized PnL, account equity, and margin ratio
are all driven by a **SIMULATED MARK PRICE** (`GET
/api/simulator/positions` and account state both carry
`mark_price_simulated: true` alongside the value) — an EMA over the real
reference price, deliberately not just the last traded price (task's own
explicit requirement). Liquidation, SL/TP, and resting-order fill checks
deliberately use the raw, unsmoothed reference price instead, since those
are consequential events that should fire against what genuinely happened
in the market. See §10 of the math doc for the exact formula and the
full where-it's-used/where-it's-not breakdown.

## Performance analytics

`GET /api/simulator/performance` computes overall stats (total/winning/
losing trades, win rate, profit factor, avg win/loss, expectancy, total
PnL/fees/funding, max drawdown, Sharpe, Sortino, liquidation count) over
every closed trade on the account, plus the same stats broken down by
side (LONG/SHORT), symbol, leverage, and strategy tag (manual vs
ai_assisted — the task's AI vs User performance comparison). Built on
`app.services.futures_sim.performance.compute_performance_stats`, a pure
function that reuses `app.services.backtest.metrics` (Sharpe/Sortino/max
drawdown/profit factor/etc.) rather than a parallel metrics engine — each
trade's ROI-on-margin feeds those ratios as its "return," the same
equity-curve-over-a-return-sequence model that module already assumes.

## Risk metrics

`GET /api/simulator/risk` classifies the account's *current* state into
warnings the dashboard can surface — margin ratio, distance to
liquidation per open position, position concentration, account drawdown,
and today's realized+unrealized PnL as a percent of equity. It is
**permissive by default**, per the task's own requirement: nothing here
blocks or rejects an action, it only labels the current state as
`HIGH_RISK` (elevated margin ratio, or a large daily loss), 
`NEAR_LIQUIDATION` (a specific position within
`futures_sim_risk_near_liquidation_pct` of its liquidation price), or
`MARGIN_WARNING` (available margin below
`futures_sim_risk_margin_warning_available_pct` of equity) — all four
thresholds are `futures_sim_risk_*` settings, not hardcoded, and each can
be overridden per-account by Max Risk Settings (below). The response's
`thresholds` object always reports the four *effective* values used for
that response (account override if set, else the global default).

`app.services.futures_sim.risk.compute_risk_metrics` is a pure function
with zero I/O: the API layer does the one query it needs (today's closed
trades, to sum `net_pnl` into `todays_realized_pnl`) and reuses the same
`get_account_state()`/mark-price-enriched positions the account and
positions endpoints already compute — no parallel data path. Distance to
liquidation is measured as a percent of the position's own mark price
(matching the mark-price-vs-raw-price scoping documented above and in
§10 of the math doc — risk display uses the same enriched positions the
`/positions` endpoint returns, so it inherits the SIMULATED mark price
there), and is `None` when a position doesn't have a liquidation price
yet.

Live-verified against the real running server: opened a real 50x BTC
long against live market data (entry 78846.14, liquidation 77584.60 —
1.58% away), confirmed `/risk` returned the same 1.58% distance and a
`NEAR_LIQUIDATION` warning naming that position, then closed the
position and confirmed `/risk` returned to a zeroed, warning-free state.

## Strategy Journal / Trade Review

Optional, per-trade annotations (task's own "optional" note) over history
that has already happened — editing them never touches PnL, fees,
balances, or any other financial field. `FuturesSimTrade` carries three
journal columns (added back in the initial schema migration,
0044_futures_simulator.py): `strategy_label` (a coarse tag — Breakout /
Trend / MeanReversion / News / AISignal / Other), `note` (free-text "why
did I enter/exit"), and `self_assessment_tags` (a Trade Review checklist
— Good Entry / Good Exit / Followed Plan / Overleveraged / Ignored Stop
Loss / FOMO Entry / Revenge Trade / Poor Risk/Reward).

`GET /api/simulator/journal-options` returns both canonical lists so the
dashboard's dropdown/checkboxes are always in sync with
`app.services.futures_sim.journal`'s own validation — never a second
hardcoded copy that could drift. `POST
/api/simulator/trades/{id}/journal` [admin] updates one trade's journal
fields; each field is optional and independent (`None` means "leave this
field unchanged", an explicit `[]` clears `self_assessment_tags`), and
the request 404s if the trade doesn't belong to the given account, 400s
if `strategy_label` or any tag isn't in the canonical list.

Live-verified with headless Chromium against the real running server:
opened and closed a real ETH position, used the Trade History tab's
Edit button to set a strategy label, two self-assessment tags, and a
note, saved, and confirmed via a direct API read that the trade's
journal fields persisted exactly as entered.

## Max Risk Settings

Optional (task's own "optional" note), per-account overrides for the
four Risk Metrics warning thresholds — `futures_sim_accounts` gained four
nullable columns (migration 0046) mirroring the `futures_sim_risk_*`
settings; a `NULL` column means "use the global default", a non-`NULL`
value overrides that one threshold for this account only. This never
changes whether an order is accepted or a position can be opened — it
only changes when a `HIGH_RISK`/`NEAR_LIQUIDATION`/`MARGIN_WARNING` label
fires in `GET /api/simulator/risk`, preserving the same
permissive-by-default philosophy as the rest of Risk Metrics.

`GET /api/simulator/risk-settings` returns the account's current
overrides alongside the global defaults (so the dashboard can show which
are customized). `POST /api/simulator/risk-settings` [admin] is a
full-replace: each of the four fields either sets that account's
override or, left `null`, reverts it to the global default — there is no
partial-update semantics here (unlike the Strategy Journal endpoint)
because there's no other meaningful value for an unset threshold to
have. `app.services.futures_sim.risk.compute_risk_metrics` takes the
resolved overrides as an optional `risk_settings_overrides` dict, still
zero I/O — the API layer reads the account's four columns and passes
them in, the function itself does no new query.

Live-verified against the real running server: set a 15% Near-Liquidation
override for a demo account through the dashboard's RISK tab, confirmed
via a direct API read that only that one field was overridden (the other
three stayed `null`), then opened a real BTC position and confirmed
`GET /risk`'s `thresholds.near_liquidation_pct` reported the overridden
15% rather than the global 5% default.

## API surface (as of this document)

```
GET    /api/simulator/account
POST   /api/simulator/account/reset        [admin]
GET    /api/simulator/symbols
POST   /api/simulator/orders               [admin]
DELETE /api/simulator/orders/{id}          [admin]  (cancels a resting order)
GET    /api/simulator/orders
GET    /api/simulator/positions
POST   /api/simulator/positions/{id}/close [admin]
POST   /api/simulator/positions/{id}/sl-tp [admin]
GET    /api/simulator/trades
POST   /api/simulator/trades/{id}/journal  [admin]
GET    /api/simulator/journal-options
GET    /api/simulator/performance
GET    /api/simulator/risk
GET    /api/simulator/risk-settings
POST   /api/simulator/risk-settings        [admin]
GET    /api/simulator/ledger
```

All mutating endpoints require the `X-Admin-Key` header
(`require_admin_key`). No endpoint accepts or stores Binance API keys or
any real exchange credential. No endpoint places, modifies, or cancels a
real order on any real exchange.

## Dashboard

A "Futures Simulator" nav item (`app/static/dashboard/app.js`,
`renderFuturesSimulator`) adds a dedicated page with 9 sub-tabs mirroring
the task's own layout: TRADE / POSITIONS / OPEN ORDERS / ORDER HISTORY /
TRADE HISTORY / PERFORMANCE / RISK / ACCOUNT HISTORY / SETTINGS. Every tab is
plain vanilla JS calling the API surface above — no new frontend
infrastructure, reusing the existing `el`/`table`/`card`/`fetchJSON`/
`fetchJSONWithAdminKey` helpers and CSS tokens the rest of the dashboard
already uses (two new button modifiers, `.controls button.buy`/`.sell`,
reuse the existing `--green`/`--red` tokens rather than introducing new
colors).

- The header shows Demo Balance/Equity/Available/Unrealized PnL/Realized
  PnL/Margin Ratio, with an explicit "PAPER TRADING / DEMO — REAL FUNDS
  NOT USED" banner always visible.
- TRADE is a two-column layout (`.trade-layout`, chart left / order panel
  right, collapsing to one column under 900px): a candlestick chart with
  timeframe tabs (5m/15m/1h/4h/1d) on the left, and OPEN LONG (green)/OPEN
  SHORT (red) buttons, symbol/leverage/margin-mode/order-type selectors,
  a live USD notional line, and price/stop-price fields that show only
  for the order types that need them, on the right.
- POSITIONS has Close 25%/50%/75%/100% buttons and an inline SL/TP
  setter per row.
- OPEN ORDERS has a Cancel button per resting order.
- TRADE HISTORY has a Journal column (a one-line summary of that trade's
  strategy label/tags/note) and an Edit button per row that opens a
  shared panel below the table — a strategy-label dropdown, self-
  assessment checkboxes, and a note field, populated from
  `GET /api/simulator/journal-options` — for the optional Strategy
  Journal / Trade Review feature.
- PERFORMANCE renders the overall stat grid plus the by-side/by-symbol/
  by-leverage/by-strategy breakdown tables.
- RISK renders `GET /api/simulator/risk`'s stat grid (margin ratio,
  available margin, max drawdown, daily PnL/loss, total exposure, open
  position count, largest position), a Warnings section (color-coded
  pills reusing the existing `decisionPill`/`.pill` system — no new CSS)
  that reads "No active warnings" when the account is healthy, an Open
  Position Risk table (notional, concentration, distance to liquidation
  per position), and a Max Risk Settings form (four optional override
  fields, each showing the global default as its placeholder, plus Save
  and Reset to Defaults buttons).
- SETTINGS has the account-name switcher (a lightweight stand-in for the
  task's "New Demo Session" concept — different account names are
  fully separate demo accounts) and the Reset Demo Account button.
- Sub-tab navigation goes through the URL (`#futures?tab=positions`), so
  each tab is a full page render via the existing `navigate()`/hash
  routing rather than a bespoke local tab switcher — consistent with how
  every other multi-view page in this dashboard already works.

Live-verified in a real headless-Chromium session against the running
server: placed a MARKET order through the UI (real BTC price, real fill),
confirmed the resulting position appeared in POSITIONS with the correct
entry/mark/margin, confirmed PERFORMANCE and ACCOUNT HISTORY rendered
real data, and confirmed the SETTINGS tab's controls render correctly.
Separately verified the RISK tab against a real 50x BTC position: the
rendered margin ratio, daily PnL, total exposure, and a NEAR_LIQUIDATION
warning naming the position all matched the API response exactly.

### Candlestick chart

`candleChart()`/`rsiPanel()` (`app/static/dashboard/app.js`) are hand-
rolled raw-SVG functions, following the same `document.createElementNS`
convention as the dashboard's existing `svgLineChart`/`svgRadarChart` —
no charting library, matching this project's no-build-step rule.
Candles + SMA 20/50/200 + RSI come straight from the existing
`GET /api/history/{symbol}?timeframe=X&limit=180` endpoint (no new
backend work for 1h/4h/1d) — every indicator drawn was already computed
and stored by `app.services.history.indicators`, reused, not
recomputed. RSI (not MACD) is the sub-panel: it has a fixed 0–100 domain
independent of the symbol's price magnitude, and its Wilder-14 warm-up
lights up ~2.5x sooner than MACD's 12/26/9, which matters once 5m
candles (below) start from zero history.

**Honesty limitation, discovered and handled deliberately, not
papered over**: CoinGecko's `/market_chart` endpoint (the source behind
`crypto_history`'s `1d`/`1h` rows) returns one price point per period,
not true OHLC — its own docstring in
`app/services/history/providers/coingecko.py` says so, and
`open=high=low=close` for every such row. So **`1d` and `1h` candles are
flat**; only `4h` (resampled from several distinct hourly points) has
genuine wicks. Rather than draw fake candle bodies for `1d`/`1h`,
`candleChart()` detects the flat case and falls back to a close-price
line + the same SMA/RSI overlays, with a visible caption naming the
reason. `5m`/`15m` render real candles once at least one has been
aggregated (see "Real 5m/15m candles" below); until then they show a
"not enough data yet" placeholder rather than an empty chart.

The crypto history sync job (`sync_crypto_daily_history_job`,
`app/scheduler/jobs.py`) was widened from DAILY-only to also keep 1h/4h
fresh on its existing hourly schedule — those two timeframes previously
only had data if a human had run a manual full sync at least once, which
would have shipped the chart with visibly stale 1h/4h tabs from day one.

Live-verified against the real running server: confirmed `4h` renders
real (non-flat) candle bodies from real synced data, confirmed `1d`
renders the honest flat-OHLC line fallback with its caption, and
confirmed `5m` shows the not-enough-data-yet placeholder before any
candle had been aggregated.

### Real 5m/15m candles

Rather than leave `5m`/`15m` permanently on the placeholder, a new
scheduled job (`aggregate_realtime_candles_job`,
`app/scheduler/jobs.py`, every `realtime_candle_interval_minutes`
— default 1 minute) rolls the live Coinbase tick feed
(`app.services.realtime.collector`, already running for the ticker/
marquee) forward into real 5m candles, one per symbol. `15m` candles
are *derived* by resampling three finished 5m candles
(`app.services.history.resample.resample_candles`, extended with a
`"15min"` rule) — never independently aggregated from ticks, so 15m can
never drift out of sync with 5m, mirroring this project's existing
4h-from-1h pattern.

Both new timeframes were added to `HistoryTimeframe`
(`app/database/models.py`) and the parallel `Timeframe` enum
(`app/services/history/schemas.py`) via migration `0047` (`ALTER TYPE
history_timeframe ADD VALUE`, same pattern as migrations `0013`/`0017`).
They are deliberately **not** added to the crypto registry's
`timeframes` tuple (what `HistorySyncEngine` asks CoinGecko to fetch —
CoinGecko has no 5m/15m support and would fail permanently) but to a
new, separate `realtime_timeframes` tuple on `HistorySymbolConfig`,
which `GET /api/history` now also accepts.

**Sampling method, stated plainly**: the job polls once a minute rather
than subscribing to every tick, so a candle's `open` can be up to ~60
seconds later than the true bucket start — every value is a real
observed price, just coarsely sampled, never fabricated. There is no
volume data (`RealtimePriceTick` only carries a rolling 24h figure, not
per-trade size), so `volume` and `volume_change_pct` are honestly
`null` on every 5m/15m row — the dashboard renders "n/a", never `0`.
Bucket state lives in Redis (`realtime:candle:5m:{SYMBOL}`, TTL
comfortably longer than one bucket) so a process restart mid-bucket
resumes from the last-known high/low/close instead of discarding real
observed data — the alternative (restart the bucket fresh) would be the
*less* honest choice, not the safer one. A stale cached tick (the feed
having gone quiet) is skipped rather than folded into the bucket, so a
disconnected symbol never produces a fabricated flat candle.

One correctness detail worth documenting: the 15m roll-up only
resamples 5m bars from *fully elapsed* 15-minute windows. Since
`upsert_candles` is `ON CONFLICT DO NOTHING`, resampling the
still-forming window and writing a premature, too-narrow 15m candle
would permanently freeze it in place — later 5m bars for that same
window would then be silently skipped as "already exists" once the
window actually completed. `_roll_up_fifteen_minute` filters those out
before resampling.

Retention: a daily job (`prune_realtime_candles_job`) deletes 5m/15m
rows older than `realtime_candle_retention_days` (default 14) — at 288
candles/day/symbol these would otherwise grow unbounded, and
`fill_missing_indicators` loads the full stored series on every call.
Pruning old rows (rather than truncating the indicator-computation
input window) is what preserves already-persisted RSI/ATR/MACD values
on the rows that remain, since those are recursive calculations.

Live-verified against the real running server and the real Coinbase
feed: started the server fresh and watched the aggregation job run
cleanly on its schedule with zero errors across real bucket rollovers
for all 10 symbols at once (`Realtime candle aggregation: 10 5m
candle(s) finalized`); confirmed a real, non-flat 5m candle (BTC:
open 79718.62 → high 79840.55 → close 79840.55, genuine price movement
across the bucket) landed in `crypto_history` and was servable via
`GET /api/history/BTC?timeframe=5m` with `volume: null`; and confirmed
the 15m roll-up correctly reflected only the single real 5m bar
available in that already-fully-elapsed window (the server had only
just started, so most of that particular 15-minute window's bars
simply don't exist yet) — an honest partial-window result, not a
fabricated one, exercising the same "resample only fully-elapsed
windows" guard the unit tests cover for the full 3-bar case.

### Live ticker marquee and Overview Open Positions widget

A horizontally auto-scrolling ticker marquee (`mountTickerMarquee()`,
pure-CSS `@keyframes` animation, no JS animation loop) sits in `#topbar`
— outside `#content`, which `render()` replaces on every navigation — so
it survives page changes without restarting its scroll. It reuses the
existing `RealtimeStore` singleton's `subscribe()` (not `.mount()`,
which would have silently broken Overview's existing `liveTicker()` grid
or itself, since `.mount()` tears down whichever component mounted
previously) — no new SSE connection, no new data source.

The Overview page also gets an **Open Positions** widget
(`renderOverviewOpenPositions()`), reading the same
`GET /api/simulator/positions?status=OPEN` the Positions tab already
uses. It is always rendered, even with zero open positions ("No open
demo positions.") — the task's own ask was that positions be visible on
the main page, so the section's presence is never itself a signal.

Live-verified against the real running server: confirmed the marquee
renders all 10 watchlist symbols and survives navigating from Overview
to the Futures Simulator page; confirmed the Overview widget in both
states — zero open positions, and a real opened ETH position (correct
symbol/side/qty/entry/mark/notional/PnL/ROI, matching the Positions tab
exactly).

### Terminal-style UI

The Futures Simulator's own pages (Trade, Positions, Orders, History,
Performance, Risk, Account History, Settings — everything under the
`#futures` route) were restyled to read as a compact dark trading
terminal, scoped entirely under the `.futures-sim` CSS class so no other
dashboard page is affected:

- **Account stat strip** — the old grid of six separate cards (Balance,
  Equity, Available, Unrealized PnL, Realized PnL, Margin Ratio) is now
  one compact bordered row (`.futures-stat-strip`), matching how
  Binance/Bybit show the account summary above the trading pane.
- **Order ticket** — the Trade tab's right column used to be a single
  flat `.controls` row of unlabeled `<select>`/`<input>` elements. It's
  now a proper order ticket card (`.order-ticket`): a header showing the
  selected symbol next to its live last price and 24h change (reusing
  `RealtimeStore`, no new data source), then labeled fields (Leverage,
  Margin Mode, Order Type, Quantity, and the LIMIT/STOP-only Price/Stop
  Price fields that show or hide based on order type), and full-width
  OPEN LONG / OPEN SHORT buttons at the bottom.
- **LONG/SHORT/BUY/SELL badges** — every table that shows a position or
  order side (Positions, Open Orders, Order History, Trade History, and
  the Risk tab's Open Position Risk table) now renders the side as a
  colored pill badge via the existing `decisionPill()` helper instead of
  plain colored text, reusing the same green/red `.pill` styling already
  used elsewhere on the dashboard rather than inventing a new color.
- Tables inside `.futures-sim` get `font-variant-numeric: tabular-nums`
  on every cell (so numeric columns line up) and a row-hover highlight.

Live-verified against the real running server with Playwright: opened
one LONG and one SHORT demo position and confirmed the badges, stat
strip, and order ticket all render correctly on desktop (1440px) and
mobile (390px) viewports, and that the Overview page (out of scope for
this pass) is unaffected.

## AI integration

The TRADE tab shows the existing GPTAgent2 forecast for the selected
symbol (`GET /api/forecast/{symbol}?horizon=24h` — the same endpoint the
AI Forecast Center on the Overview page already uses, no new forecast
computation): Current Forecast (direction), Probability, Confidence,
Regime, Expected Move, and Historical Edge (the forecast's own
track-record win rate).

**The AI forecast never opens a demo position by itself.** A "USE AI
SIGNAL" button (disabled when the forecast is `Neutral`) only pre-fills
two SL/TP suggestion fields on the order form, derived from the
forecast's `key_levels` (support/resistance) and `target_price`. Those
fields stay editable and are applied to the resulting position only if
the user goes on to click OPEN LONG/OPEN SHORT themselves — the same
explicit click that submits the order also carries whatever is in the
SL/TP fields at that moment, applied via `POST
/api/simulator/positions/{id}/sl-tp` right after the position opens. No
code path anywhere calls `POST /api/simulator/orders` from forecast data
without that user click in between.

Live-verified in a real headless-Chromium session: loaded the forecast
panel for a symbol with a real `Bullish` signal, clicked USE AI SIGNAL,
confirmed the SL/TP fields were pre-filled with real support/resistance-
derived values (not submitted), then clicked OPEN LONG and confirmed via
the API that the resulting position's `sl_price`/`tp_price` matched
exactly what had been pre-filled.

## Known limitations

Tracked in full in `docs/FUTURES_SIMULATOR_MATH.md`'s "Known limitations"
section — summarized here:

- Funding settles on a fixed schedule (not the split-second timestamp a
  real exchange settles at) and is not proportionally allocated on a
  partial close — see §13 of the math doc.
- Resting orders (LIMIT/STOP_MARKET/TAKE_PROFIT_MARKET) do not reserve
  margin at placement time; they are re-checked at fill time and can be
  REJECTED then if margin has become insufficient in the meantime.
- The candlestick chart's `1d`/`1h` timeframes render a close-price line,
  not real candle bodies — CoinGecko's price-history endpoint returns one
  price point per period for those timeframes, not true OHLC (see the
  Dashboard section's "Candlestick chart" subsection). Only `4h` has
  genuine wicks today.
- `5m`/`15m` candles are real but coarsely sampled — the aggregation job
  polls the tick feed once a minute rather than subscribing to every
  tick, so a candle's `open` can be up to ~60 seconds later than the
  true bucket start. Every value is a real observed price, never
  fabricated; see the Dashboard section's "Real 5m/15m candles"
  subsection. There is also no volume data on these rows (`null`, not
  `0`) — the tick feed carries only a rolling 24h figure, not per-trade
  size.
- `5m`/`15m` history only exists from whenever this feature first
  deployed forward — there is no honest historical backfill at this
  resolution (no free provider supports it), so a freshly reset/redeployed
  instance briefly shows the "not enough data yet" placeholder again
  until a few candles accumulate.
- The chart has no crosshair/hover OHLC readout yet, and only RSI (not
  MACD) is available as an indicator sub-panel — both are documented,
  deliberately deferred polish, not oversights.
- No historical-replay trading mode yet.
- The AI signal's suggested SL/TP levels come from the forecast's own
  `key_levels` (support/resistance) and `target_price` — a reasonable
  but simplified mapping (bullish: SL at support, TP at target/resistance;
  bearish: the mirror), not a dedicated risk-sized suggestion.
- OPEN ORDERS is client-side filtered from the full order-history fetch
  (`status === "NEW"`) rather than a dedicated server-side filter — fine
  at demo-account order volumes.
- Performance breakdowns (`by_side`/`by_symbol`/`by_leverage`/`by_strategy`)
  compute over every closed trade with no pagination or date-range filter
  yet — fine at demo-account trade volumes, would need one at scale.
- Max Risk Settings only override the four Risk Metrics warning
  thresholds — it does not (and, per the task's own permissive-by-default
  philosophy, should not) block orders, cap leverage, or enforce position
  limits; it purely changes when a warning label appears.

## Confirmations

- REAL MONEY: NO
- REAL EXCHANGE ORDERS: NO
- REAL BINANCE API KEYS: NO
- REAL MARKET DATA: YES (drives every fill's reference price, where
  available)
- DEMO TRADING: YES
