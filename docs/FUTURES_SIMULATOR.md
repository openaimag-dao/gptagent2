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
  (`DEPOSIT` / `RESET` / `OPEN` / `FEE` / `REALIZED_PNL`, more event types
  as funding/withdrawal-style events are added), each row carrying the
  exact signed `amount` and the resulting `balance_after`.

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
GET    /api/simulator/performance
GET    /api/simulator/ledger
```

All mutating endpoints require the `X-Admin-Key` header
(`require_admin_key`). No endpoint accepts or stores Binance API keys or
any real exchange credential. No endpoint places, modifies, or cancels a
real order on any real exchange.

## Dashboard

A "Futures Simulator" nav item (`app/static/dashboard/app.js`,
`renderFuturesSimulator`) adds a dedicated page with 8 sub-tabs mirroring
the task's own layout: TRADE / POSITIONS / OPEN ORDERS / ORDER HISTORY /
TRADE HISTORY / PERFORMANCE / ACCOUNT HISTORY / SETTINGS. Every tab is
plain vanilla JS calling the API surface above — no new frontend
infrastructure, reusing the existing `el`/`table`/`card`/`fetchJSON`/
`fetchJSONWithAdminKey` helpers and CSS tokens the rest of the dashboard
already uses (two new button modifiers, `.controls button.buy`/`.sell`,
reuse the existing `--green`/`--red` tokens rather than introducing new
colors).

- The header shows Demo Balance/Equity/Available/Unrealized PnL/Realized
  PnL/Margin Ratio, with an explicit "PAPER TRADING / DEMO — REAL FUNDS
  NOT USED" banner always visible.
- TRADE has OPEN LONG (green)/OPEN SHORT (red) buttons, symbol/leverage/
  margin-mode/order-type selectors, and price/stop-price fields that show
  only for the order types that need them.
- POSITIONS has Close 25%/50%/75%/100% buttons and an inline SL/TP
  setter per row.
- OPEN ORDERS has a Cancel button per resting order.
- PERFORMANCE renders the overall stat grid plus the by-side/by-symbol/
  by-leverage/by-strategy breakdown tables.
- SETTINGS has the account-name switcher (a lightweight stand-in for the
  task's "New Demo Session" concept — different account names are
  fully separate demo accounts) and the Reset Demo Account button.
- Sub-tab navigation goes through the URL (`#futures?tab=positions`), so
  each tab is a full page render via the existing `navigate()`/hash
  routing rather than a bespoke local tab switcher — consistent with how
  every other multi-view page in this dashboard already works.
- No candlestick/TradingView-style chart yet on the TRADE tab (see Known
  Limitations) — the only charting primitive in this dashboard today is a
  single-series SVG line chart with no OHLC support.

Live-verified in a real headless-Chromium session against the running
server: placed a MARKET order through the UI (real BTC price, real fill),
confirmed the resulting position appeared in POSITIONS with the correct
entry/mark/margin, confirmed PERFORMANCE and ACCOUNT HISTORY rendered
real data, and confirmed the SETTINGS tab's controls render correctly.

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

- Funding is not implemented (`funding` is always `0.0` in every PnL
  calculation).
- Resting orders (LIMIT/STOP_MARKET/TAKE_PROFIT_MARKET) do not reserve
  margin at placement time; they are re-checked at fill time and can be
  REJECTED then if margin has become insufficient in the meantime.
- Mark price is the raw last observed price; the EMA-smoothed "SIMULATED
  MARK PRICE" formula exists as a pure function but isn't wired into live
  position updates yet.
- No candlestick/TradingView-style price chart on the TRADE tab yet — this
  dashboard has no OHLC charting primitive anywhere today, only a single-
  series SVG line chart; building one is a dedicated future increment.
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

## Confirmations

- REAL MONEY: NO
- REAL EXCHANGE ORDERS: NO
- REAL BINANCE API KEYS: NO
- REAL MARKET DATA: YES (drives every fill's reference price, where
  available)
- DEMO TRADING: YES
