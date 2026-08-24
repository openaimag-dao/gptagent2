# Futures Simulator — Math Reference

**Scope:** every formula the Futures Simulator uses to compute margin,
PnL, fees, mark price, and liquidation. This is a 100% demo/paper-trading
system — no real money, no real Binance orders, no real exchange
credentials anywhere in this codebase. Real market data (price/candles)
drives every fill's reference price; only the account/position/order
state is simulated. See `docs/FUTURES_SIMULATOR.md` for the feature-level
overview and `app/services/futures_sim/engine.py` for the pure-function
implementations these formulas correspond to 1:1.

Every formula below is implemented as a small, independently unit-tested
pure function (`tests/test_futures_sim_engine.py`) — nothing here is
computed inline at the call site.

---

## 1. Notional, initial margin, maintenance margin

```
notional            = quantity * price
initial_margin      = notional / leverage
maintenance_margin  = notional * maintenance_margin_pct / 100
```

`initial_margin` is the textbook definition of leverage. `maintenance_margin_pct`
comes from the position's **SIMULATED leverage bracket** — see §7 — never
a fixed constant.

## 2. Fees

```
fee_amount = notional * fee_rate_pct / 100
```

`fee_rate_pct` is `futures_sim_maker_fee_pct` or `futures_sim_taker_fee_pct`
(settings-driven, never hardcoded at the call site). MARKET orders are
always taker fills; the maker rate exists for when LIMIT resting-order
fills are added.

**Flip / reduceOnly-cap correctness:** because fee is *linear* in notional,
`fee(a) + fee(b) == fee(a + b)`. When one order both closes an existing
position and opens a new one in the opposite direction ("flip", §5), the
close leg's fee is computed on the quantity actually closed and the open
leg's fee on the remainder — never on the full requested quantity for
both legs, which would double-charge the overlap. A reduceOnly order that
gets capped (requested quantity exceeds the open position) is charged only
on the quantity that actually executed; the discarded remainder is never
filled and never charged.

## 3. Market order fill (slippage)

```
direction   = +1 for BUY, -1 for SELL
fill_price  = reference_price * (1 + direction * slippage_pct / 100)
```

Slippage always moves the fill *against* the trader — a BUY pays slightly
more than the reference price, a SELL receives slightly less — matching
how real market impact works, never a fill that favors the trader.
`slippage_pct` is `futures_sim_market_slippage_pct` (settings-driven).
`requested_price` (the reference price) and `estimated_fill_price` /
`actual_fill_price` (identical today, kept as separate fields for a future
more realistic partial-fill model) are all persisted on the order row.

## 4. Position PnL

```
LONG:  gross_pnl = (mark_price - entry_price) * quantity
SHORT: gross_pnl = (entry_price - mark_price) * quantity

net_pnl = gross_pnl - fees - funding - slippage_cost
```

`net_pnl` is realized PnL at close time and unrealized PnL (against the
live mark price) while a position stays open — same formula either way,
the only difference is which price feeds `mark_price`. `funding` is
currently always `0.0` (funding is not yet implemented — see
`docs/FUTURES_SIMULATOR.md`'s Known Limitations). `slippage_cost` is not
separately itemized today; slippage's PnL effect is already folded into
`gross_pnl` via the fill price computed in §3.

## 5. Position lifecycle (ONE-WAY mode)

At most one open position per `(account, symbol)`. An order against an
existing position does one of:

- **Increase** (same direction): weighted-average entry price,
  `new_entry = (old_entry*old_qty + fill_price*added_qty) / new_qty` — the
  standard exchange convention for adding to a position, not an
  approximation.
- **Reduce / close** (opposite direction, `quantity <= position.quantity`):
  realizes PnL on the closed quantity via §4; any remaining quantity keeps
  its original entry price.
- **Flip** (opposite direction, `quantity > position.quantity`, not
  `reduceOnly`): closes the existing position fully, then opens a new
  position in the new direction sized at the excess quantity — exactly how
  a real one-way-mode exchange nets a single oversized order.
- **reduceOnly cap**: if `reduceOnly=True` and the requested quantity
  exceeds the position, the close is capped at the position's own size;
  the excess is never filled and never flips into a new position.

## 6. ROI

```
roi_pct = 100 * pnl / margin      (None if margin == 0, never a
                                    fabricated infinite ROI)
```

Worked example from the task spec: margin = $500, gross PnL = +$100 →
ROI = +20%. ROI is on the position's own margin, deliberately kept
separate from the account's overall equity return (§9).

## 7. Leverage brackets (SIMULATED)

`FUTURES_LEVERAGE_BRACKETS` in `engine.py` gives each of the simulator's
10 supported symbols a flat `(max_leverage, maintenance_margin_pct)` tier,
loosely ordered by real-world liquidity (deep majors get more leverage
headroom, smaller caps get less) **without claiming to be sourced from any
real exchange's tiered notional brackets**. A symbol missing from the
table falls back to `futures_sim_default_max_leverage` /
`futures_sim_default_maintenance_margin_pct`. These brackets are
explicitly labeled `bracket_is_simulated: true` everywhere they're
surfaced (`GET /api/simulator/symbols`) — never presented as real Binance
limits.

## 8. Liquidation price

### 8a. ISOLATED margin

```
LONG:  liq_price = entry_price * (1 - 1/leverage + maintenance_margin_pct/100)
SHORT: liq_price = entry_price * (1 + 1/leverage - maintenance_margin_pct/100)
```

**Derivation:** a position liquidates once its margin balance (initial
margin ± unrealized PnL) falls to its maintenance margin. Substituting
`initial_margin = notional/leverage` and
`maintenance_margin = notional*maintenance_margin_pct/100` into §4's PnL
formula and solving for the `mark_price` at which
`initial_margin + unrealized_pnl == maintenance_margin` gives exactly the
formulas above — the `quantity`/`notional` terms cancel, leaving a pure
function of `entry_price`, `leverage`, and `maintenance_margin_pct`.

**Known simplification** (documented per the task's own requirement to
never ship an undocumented simplified formula): this ignores the exact
taker-fee cost of the liquidating fill itself. A real exchange's
liquidation price sits fractionally closer to entry once that fee is
netted in; this simulator's liquidation price is therefore very slightly
more conservative (later) than a real exchange's would be for the same
inputs. Acceptable for a training/paper-trading tool; documented here
rather than silently baked in.

### 8b. CROSS margin

```
cushion   = other_account_equity + initial_margin - maintenance_margin
LONG:  liq_price = entry_price - cushion / quantity
SHORT: liq_price = entry_price + cushion / quantity
```

where `other_account_equity` is the account's total equity **excluding**
this position's own initial margin and unrealized PnL — i.e.
`wallet_balance + sum(unrealized PnL of every OTHER open position)`.

**Derivation:** liquidates when
`other_account_equity + initial_margin + unrealized_pnl == maintenance_margin`.
Solving §4's PnL formula for the `mark_price` at that point gives the
formulas above.

**Why CROSS liquidates later than ISOLATED (usually):** the rest of the
account's equity adds to the cushion beyond the position's own initial
margin, so a healthy account pushes a CROSS position's liquidation price
further from entry than the same position would have in ISOLATED mode. A
account that is *already underwater* on its other positions
(`other_account_equity < 0`) does the opposite — it pulls the liquidation
price closer to entry, exactly as real cross-margin risk-sharing works.

**Recomputed on every position mutation** (open, increase, partial
close) that changes `entry_price`, `quantity`, `initial_margin`, or
`maintenance_margin` — for CROSS positions this means re-querying every
other open position's current mark price on each recompute
(`_other_open_positions_unrealized_pnl` in `orders.py`), since
`other_account_equity` is a live number, not a cached one.

## 9. Account equity (always derived live, never cached)

```
equity            = wallet_balance + unrealized_pnl
used_margin       = sum(initial_margin of every OPEN position)
available_margin  = equity - used_margin
margin_ratio      = 100 * used_margin / equity   (None if equity <= 0)
```

`wallet_balance`, `realized_pnl_total`, `fees_paid_total`, and
`funding_paid_total` are the only account fields persisted incrementally
(each mutated exactly once per event, inside the same DB transaction that
creates the corresponding ledger entry). `equity`, `unrealized_pnl`,
`used_margin`, `available_margin`, `margin_ratio`, and
`maintenance_margin_total` are **always** recomputed from the account's
current open positions against live mark prices in
`FuturesSimEngine.get_account_state()` — never read from a stale stored
column. `peak_equity` / `max_drawdown_pct` are the one exception that
genuinely needs persisting (a high-water mark can't be recovered from
current state alone) and are ratcheted forward whenever a freshly computed
equity exceeds the stored peak.

## 10. Mark price (SIMULATED MARK PRICE)

```
mark = alpha * reference_price + (1 - alpha) * previous_mark      # alpha = 0.3 default
```

An exponential moving average over the real reference price — deliberately
**not** just the latest traded price (the task's own explicit
requirement), since this project has no separate real index-price feed to
blend with the way a real exchange's mark price does.
`engine.get_mark_price()` applies this incrementally: the previous EMA
value is persisted in Redis per symbol (`futures_sim:mark_ema:{symbol}`,
1-hour TTL) and blended with each newly observed real reference price
from `get_current_price()` — mathematically identical to
`compute_simulated_mark_price()`'s own list-based formula (still used
directly by its own unit tests), without needing to store a price
history. Every response carries `mark_price_simulated: true` alongside
the value, and the raw `reference_price` it was blended from, so a
consumer never has to guess.

**Where it's used:** account/position unrealized PnL, equity, and margin
ratio (`FuturesSimEngine.get_account_state()`) and the `GET
/api/simulator/positions` live-enrichment path — matching how mark price
drives PnL/margin on a real exchange too.

**Where it's deliberately NOT used:** liquidation/SL/TP trigger checks
(`app.services.futures_sim.monitor`) and resting-order fill checks
(`app.services.futures_sim.resting_orders`) both check the raw,
unsmoothed reference price from `get_current_price()` — a liquidation or
a resting order's fill is a real, consequential event and should fire
against what genuinely happened in the market, not a smoothed lagging
value that could delay or advance it.

## 11. Liquidation / SL / TP monitoring

`app.services.futures_sim.monitor.check_positions_for_triggers` runs on a
schedule (`futures_sim_position_monitor_interval_minutes`, default every
1 minute) and, for every OPEN position, checks the current mark price
against three trigger prices in strict priority order:

```
LIQUIDATION > STOP_LOSS > TAKE_PROFIT
```

Liquidation always wins if a position has somehow crossed multiple
triggers on the same check (e.g. a price gap straight through both a
stop-loss and the liquidation price) — it is the more severe and more
realistic outcome. All three use the same directional comparison:

```
LONG:  triggers when mark_price <= trigger_price
SHORT: triggers when mark_price >= trigger_price
```

for the LONG's liquidation price and stop-loss (a LONG loses value as
price falls) and the mirror-image comparison for take-profit (a LONG
gains as price rises, so TP triggers on `mark_price >= tp_price`). A
triggered position is closed through the exact same `close_position()`
primitive a manual close uses, with `exit_reason` set to whichever trigger
fired — so a liquidation, stop-loss, or take-profit produces the same
`FuturesSimTrade` row, wallet-balance update, and ledger entries a manual
close would, just with a different `exit_reason` label.

**SL/TP validation** (`set_stop_loss_take_profit` in `orders.py`): a
stop-loss/take-profit that sits on the wrong side of entry is rejected at
set time — a LONG's stop-loss must be below entry and its take-profit
above; SHORT is the mirror image. An inverted SL/TP would either never
trigger or trigger immediately, neither of which is what "stop loss" or
"take profit" means.

## 12. LIMIT / STOP_MARKET / TAKE_PROFIT_MARKET fills

`app.services.futures_sim.resting_orders.check_resting_orders_for_fills`
runs on the same schedule as §11's position monitor and, for every
`status=NEW` resting order, checks:

```
LIMIT:                          BUY triggers when price <= order.price
                                 SELL triggers when price >= order.price
STOP_MARKET / TAKE_PROFIT_MARKET: BUY triggers when price >= order.stop_price
                                   SELL triggers when price <= order.stop_price
```

A LIMIT fill uses `order.price` directly as its `actual_fill_price` — no
slippage, since a guaranteed price is the entire point of a limit order.
A triggered STOP_MARKET/TAKE_PROFIT_MARKET fills exactly like a MARKET
order (§3) against the current price at the moment it triggers, since
from that moment on it genuinely is a market order.

Both order types share the identical trigger *direction* despite being
used for opposite intents (a protective stop vs. a target) — this matches
real exchange semantics, where STOP_MARKET and TAKE_PROFIT_MARKET differ
only in labeling/intended use, not in execution mechanics.

**Deterministic fill model** (task's own stated preference over an
unrealistic partial-fill simulation): this simulator has no order book,
so a resting order either fills completely or stays `NEW` — never
`PARTIALLY_FILLED`.

**Margin is not reserved at placement time.** A resting order's margin
sufficiency is checked again at fill time (the same check an immediate
MARKET fill already does); if the account's available margin has fallen
below what the order would need by the time it fills, the order is
REJECTED then rather than being pre-validated and reserved when placed.

## 13. Funding

```
notional     = quantity * mark_price
funding_fee  = notional * funding_rate_pct / 100
signed_fee   = funding_fee   if side == LONG   (LONG pays when the rate is positive)
             = -funding_fee  if side == SHORT  (SHORT is the exact mirror)
```

`app.services.futures_sim.funding.apply_funding_to_open_positions` runs
on a schedule (`futures_sim_funding_interval_hours`, default every 8
hours — matching real exchanges' own settlement cadence) and, for every
OPEN position, debits (or credits, when `signed_fee` is negative)
`account.wallet_balance` directly and accumulates the amount on
`position.funding_paid`.

**Real vs. SIMULATED** (task: "Funding using real data if available else
'unavailable', simulated funding explicitly labeled SIMULATED"):
`funding_rate_pct` comes from `WhaleIntelligenceEngine.get_snapshot()` —
the same CoinGlass-primary/CoinGecko-derivatives-fallback source the
Whale Intelligence page already uses, no new market-data integration.
CoinGecko's `funding_rate` field is already a percentage (verified
directly against its live `/derivatives` response: a raw value of
`0.007731` for Binance's BTCUSDT perpetual corresponds to Binance's own
displayed `0.0077%` funding rate, not `0.7731%`), so no unit conversion
happens beyond that. When neither source has a rate for a symbol, the
configured `futures_sim_simulated_funding_rate_pct` is used instead, and
every ledger entry it produces is labeled `SIMULATED` in its
description — never presented as real.

**Reporting on closed trades:** funding is debited/credited to the
wallet the moment it's charged, exactly like a real exchange — it is
*not* subtracted again from `net_pnl` at position-close time.
`FuturesSimTrade.funding` is a pure reporting field, set to the
position's accumulated `funding_paid` only when a close fully closes the
position (a partial close leaves the accumulated funding attributed to
the remaining position rather than proportionally splitting it — a
documented simplification).

## 14. Risk metrics

```
distance_to_liquidation_pct = 100 * (mark_price - liquidation_price) / mark_price   (LONG)
                             = 100 * (liquidation_price - mark_price) / mark_price   (SHORT)

concentration_pct[i]        = 100 * notional[i] / sum(notional)

daily_pnl                   = todays_realized_pnl + unrealized_pnl
daily_loss_pct               = -100 * daily_pnl / equity   (only when daily_pnl < 0, else None)
```

`app.services.futures_sim.risk.compute_risk_metrics` is a pure, zero-I/O
function over data the API layer already has — the same mark-price-
enriched positions §10 describes and the `get_account_state()` equity/
margin-ratio/available-margin the account endpoint already computes.
`todays_realized_pnl` is the caller's own responsibility (sum of today's
closed trades' `net_pnl`); this function does no trade-history query
itself. Warning thresholds (`futures_sim_risk_high_margin_ratio_pct`,
`futures_sim_risk_near_liquidation_pct`,
`futures_sim_risk_margin_warning_available_pct`,
`futures_sim_risk_daily_loss_warning_pct`) are all configurable settings,
never hardcoded — and, per the task's own "permissive by default"
requirement, none of them block or reject anything; they only classify
the account's current state for display.

---

## Known limitations (as of this document)

- The ISOLATED liquidation formula (§8a) does not net in the liquidating
  fill's own taker fee.
- The persisted `futures_sim_positions.mark_price` column (set at open/
  increase time) is never updated after that — §10's live SIMULATED MARK
  PRICE is always computed fresh at read time instead, so the stored
  column is a historical snapshot only, never read for PnL/display.
- Resting orders (§12) do not reserve margin at placement time; a
  documented simplification versus a real exchange's margin-reservation
  model.
- Funding (§13) uses `mark_price` (the position's own last-recorded
  price) rather than a freshly-fetched price at settlement time, and
  settles on a fixed schedule rather than the split-second timestamp a
  real exchange settles at.
- Funding on a partial close is not proportionally allocated between the
  closed and remaining quantity (§13) — it stays with the remaining
  position until it fully closes.
- The position monitor (§11) and the resting-order fill check (§12) both
  poll on a schedule rather than reacting instantly to every price tick —
  a position/order can theoretically remain past its trigger price for up
  to one polling interval before being auto-closed/filled. Fine for a
  training tool; not a claim of real-time exchange-grade latency.
- Risk metrics' `distance_to_liquidation_pct` (§14) is `None` for a
  position without a computed liquidation price yet (see §8b's own
  documented CROSS-margin deferral), and `daily_loss_pct`/`daily_pnl`
  depend on the caller supplying `todays_realized_pnl` correctly — the
  function itself does no trade-history query.
