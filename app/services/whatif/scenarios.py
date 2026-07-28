"""Scenario Simulator -- v4.0 Phase 5. Named "what if X happens" shocks,
each answered with the best real data this platform already computes:

- If the shock has a genuine historical analog (an EconomicCalendarEvent
  or HistoricalEvent category), its expected impact on BTC/ETH/SOL is the
  empirical average 7-day forward return across every real past
  occurrence (via EventImpactEngine), with the sample size shown --
  never fabricated, and honestly falls back to the heuristic case when
  there are zero occurrences.
- Else if the shock corresponds to a tracked correlation pair (DXY,
  NASDAQ, ...), the directional lean is derived from the real stored
  Pearson correlation coefficient (CorrelationEngine) times the shock's
  direction -- a qualitative lean, not a magnitude, since a correlation
  coefficient isn't a regression slope and turning it into a percentage
  would overstate precision this platform doesn't have.
- Else (no historical analog and no tracked correlation exists for this
  shock, e.g. "SOL ETF approved" has never happened before), the
  reasoning is explicitly labeled illustrative rather than empirical.

This mirrors ScenarioEngine's own documented philosophy (deterministic,
documented weighting, never an LLM-invented number) -- applied here to
named point-in-time shocks instead of ambient macro regimes.
"""

from dataclasses import dataclass

_CORRELATION_LEAN_THRESHOLD = 0.15


@dataclass(frozen=True)
class ShockDefinition:
    key: str
    label: str
    description: str
    regime_shift_toward: str  # a MarketRegime value this shock would push toward
    risk_direction: str  # "up" | "down" | "unchanged"
    liquidity_direction: str  # "up" | "down" | "unchanged"
    heuristic_note: str
    event_category: str | None = None  # EconomicCalendarCategory/HistoricalEventCategory value
    correlation_symbol: str | None = None  # other side of a tracked BTC-{symbol} pair
    correlation_shock_sign: int = 0  # +1 if correlation_symbol rises in this scenario, -1 if falls


SHOCKS: tuple[ShockDefinition, ...] = (
    ShockDefinition(
        key="fed_cuts_rates",
        label="Fed Cuts Rates",
        description="The Federal Reserve cuts its target rate at an FOMC meeting.",
        event_category="fomc",
        regime_shift_toward="liquidity_expansion",
        risk_direction="down",
        liquidity_direction="up",
        heuristic_note=(
            "Rate cuts historically ease financial conditions and support risk assets. "
            "Note: FOMC dates cover every meeting outcome (hikes, cuts, holds) -- this "
            "platform does not store which way each historical decision went, so the "
            "empirical average below is across all FOMC meetings, not cuts specifically."
        ),
    ),
    ShockDefinition(
        key="etf_inflows_double",
        label="ETF Inflows Double",
        description="Spot BTC ETF net inflows double from their current pace.",
        regime_shift_toward="accumulation",
        risk_direction="down",
        liquidity_direction="up",
        heuristic_note=(
            "Sustained ETF buying pressure is a documented institutional-demand tailwind "
            "for BTC. No historical analog for a literal inflow-doubling event exists in "
            "this platform to measure empirically, and no dollar-flow data source is "
            "configured (see ETFIntelligenceEngine) -- illustrative only."
        ),
    ),
    ShockDefinition(
        key="dxy_drops",
        label="DXY Drops",
        description="The US Dollar Index (DXY) falls meaningfully.",
        correlation_symbol="DXY",
        correlation_shock_sign=-1,
        regime_shift_toward="risk_on",
        risk_direction="down",
        liquidity_direction="up",
        heuristic_note=(
            "A weaker dollar has historically coincided with strength in risk assets "
            "including BTC; direction below is derived from the real stored BTC-DXY "
            "correlation coefficient, not a fabricated magnitude."
        ),
    ),
    ShockDefinition(
        key="oil_spikes",
        label="Oil Spikes",
        description="Crude oil prices spike sharply.",
        regime_shift_toward="risk_off",
        risk_direction="up",
        liquidity_direction="down",
        heuristic_note=(
            "Oil-driven inflation pressure has historically tightened financial "
            "conditions and pressured risk assets. This platform does not track an "
            "OIL correlation pair, so no empirical or correlation-based estimate is "
            "available here -- illustrative only."
        ),
    ),
    ShockDefinition(
        key="nasdaq_crashes",
        label="Nasdaq Crashes",
        description="The Nasdaq falls sharply in a broad equity selloff.",
        correlation_symbol="NASDAQ",
        correlation_shock_sign=-1,
        regime_shift_toward="risk_off",
        risk_direction="up",
        liquidity_direction="down",
        heuristic_note=(
            "Crypto has historically traded as a high-beta risk asset alongside tech "
            "equities; direction below is derived from the real stored BTC-NASDAQ "
            "correlation coefficient, not a fabricated magnitude."
        ),
    ),
    ShockDefinition(
        key="btc_loses_support",
        label="BTC Loses Support",
        description="BTC breaks down through a key technical support level.",
        event_category="crash",
        regime_shift_toward="distribution",
        risk_direction="up",
        liquidity_direction="down",
        heuristic_note=(
            "Empirical returns below are averaged across this platform's curated "
            "historical crash events (see HistoricalEvent), which vary widely in "
            "severity -- treat the average as directional context, not a precise "
            "forecast for any single support break."
        ),
    ),
    ShockDefinition(
        key="sol_etf_approved",
        label="SOL ETF Approved",
        description="A spot Solana ETF is approved by regulators.",
        regime_shift_toward="altseason",
        risk_direction="down",
        liquidity_direction="up",
        heuristic_note=(
            "No spot Solana ETF has ever been approved historically, so there is no "
            "analog to measure empirically -- illustrative only, based on the same "
            "institutional-demand reasoning as a BTC/ETH ETF approval."
        ),
    ),
)

SHOCKS_BY_KEY: dict[str, ShockDefinition] = {shock.key: shock for shock in SHOCKS}


def average_forward_return(
    occurrences: list[dict], key: str = "return_7d_pct"
) -> tuple[float | None, int]:
    """Mean of a real historical field across every occurrence that has
    it -- None/0 (not a fabricated 0.0) when there's nothing to average."""
    values = [o[key] for o in occurrences if o.get(key) is not None]
    if not values:
        return None, 0
    return round(sum(values) / len(values), 2), len(values)


def correlation_direction(correlation: float | None, shock_sign: int) -> str | None:
    """Qualitative lean only -- deliberately not a percentage, since a
    Pearson correlation coefficient isn't a regression slope and treating
    it as one would overstate precision this platform doesn't have."""
    if correlation is None or shock_sign == 0:
        return None
    net = correlation * shock_sign
    if net > _CORRELATION_LEAN_THRESHOLD:
        return "bullish"
    if net < -_CORRELATION_LEAN_THRESHOLD:
        return "bearish"
    return "neutral"
