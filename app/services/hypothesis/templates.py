"""Hypothesis templates (V3 Phase 8): "{SYMBOL} reacts stronger to {EVENT_A}
than to {EVENT_B}" -- generated from real, existing event categories
(app/services/research/events_lookup.py), never invented ones."""

from dataclasses import dataclass

DEFAULT_SYMBOLS: tuple[str, ...] = ("BTC", "ETH", "SPX", "NASDAQ")
DEFAULT_EVENT_PAIRS: tuple[tuple[str, str], ...] = (
    ("fomc", "cpi"),
    ("halving", "cpi"),
    ("crash", "macro_policy"),
    ("nfp", "gdp"),
    ("black_swan", "regulatory"),
)


@dataclass(frozen=True)
class HypothesisTemplate:
    symbol: str
    event_a: str
    event_b: str

    @property
    def statement(self) -> str:
        return (
            f"{self.symbol} reacts stronger to {self.event_a.upper()} "
            f"than to {self.event_b.upper()}"
        )


def generate_hypotheses(
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
    event_pairs: tuple[tuple[str, str], ...] = DEFAULT_EVENT_PAIRS,
) -> list[HypothesisTemplate]:
    return [
        HypothesisTemplate(symbol=symbol, event_a=a, event_b=b)
        for symbol in symbols
        for a, b in event_pairs
    ]
