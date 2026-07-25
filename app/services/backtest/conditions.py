"""A small, safe, structured condition DSL for rules -- deliberately not a
free-text/NLP parser or arbitrary code eval. A rule is an AND of Conditions,
each a (symbol, field, operator, value) triple evaluated against that
symbol's already-computed history fields (rsi, sma_50, return_pct, ...).
Pure and unit-testable; no I/O.
"""

from dataclasses import dataclass

_OPERATORS = {
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "gte": lambda a, b: a >= b,
    "lte": lambda a, b: a <= b,
}


@dataclass(frozen=True)
class Condition:
    symbol: str
    field: str
    operator: str
    value: float

    def __post_init__(self) -> None:
        if self.operator not in _OPERATORS:
            raise ValueError(f"Unsupported operator: {self.operator!r} (use gt/lt/gte/lte)")


def evaluate_condition(row: dict, condition: Condition) -> bool | None:
    """None means "can't evaluate" (missing field) -- never guessed as True/False."""
    value = row.get(condition.field)
    if value is None:
        return None
    return _OPERATORS[condition.operator](value, condition.value)


def evaluate_rule(
    rows_by_symbol: dict[str, dict | None], conditions: list[Condition]
) -> bool | None:
    """rows_by_symbol: {symbol: {field: value, ...} | None} for one aligned date.
    Returns None (not False) if any referenced symbol/field is missing that date,
    so a rule never fires on incomplete data."""
    if not conditions:
        return None
    for condition in conditions:
        row = rows_by_symbol.get(condition.symbol)
        if row is None:
            return None
        result = evaluate_condition(row, condition)
        if result is None:
            return None
        if not result:
            return False
    return True
