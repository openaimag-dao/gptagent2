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

## 10. Mark price (SIMULATED when smoothed)

```
mark = recent_prices[0]
for price in recent_prices[1:]:
    mark = alpha * price + (1 - alpha) * mark          # alpha = 0.3 default
```

An exponential moving average over recently observed real prices —
deliberately **not** just the latest traded price (the task's own explicit
requirement), since this project has no separate real index-price feed to
blend with the way a real exchange's mark price does. `compute_simulated_mark_price`
exists as a pure function today; it is not yet wired into the live
position `mark_price` field or `get_current_price()` (both currently use
the raw last observed tick/candle price directly) — wiring the EMA
smoothing into periodic mark-price updates is a documented, deferred
increment. Any consumer of a smoothed value must label it "SIMULATED MARK
PRICE," never present it as sourced from a real exchange.

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

---

## Known limitations (as of this document)

- Funding is not yet implemented; `funding` is hardcoded to `0.0` in every
  PnL calculation.
- The ISOLATED liquidation formula (§8a) does not net in the liquidating
  fill's own taker fee.
- Mark price smoothing (§10) exists as a pure function but is not yet
  wired into live position updates — `mark_price` is currently the raw
  last observed price.
- Resting orders (§12) do not reserve margin at placement time; a
  documented simplification versus a real exchange's margin-reservation
  model.
- The position monitor (§11) and the resting-order fill check (§12) both
  poll on a schedule rather than reacting instantly to every price tick —
  a position/order can theoretically remain past its trigger price for up
  to one polling interval before being auto-closed/filled. Fine for a
  training tool; not a claim of real-time exchange-grade latency.
