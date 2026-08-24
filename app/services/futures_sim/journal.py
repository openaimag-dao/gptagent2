"""Futures Simulator -- Strategy Journal / Trade Review (task: optional,
per-trade notes over already-closed history). Purely a note-taking layer:
editing these fields never touches PnL, fees, balances, or anything
financial -- it only annotates a FuturesSimTrade row that already exists.

The canonical label/tag lists mirror FuturesSimTrade's own docstring
(app/database/models.py) so the API's validation and the dashboard's
dropdown/checkboxes never drift out of sync with each other."""

STRATEGY_LABELS = ["Breakout", "Trend", "MeanReversion", "News", "AISignal", "Other"]

SELF_ASSESSMENT_TAGS = [
    "Good Entry",
    "Good Exit",
    "Followed Plan",
    "Overleveraged",
    "Ignored Stop Loss",
    "FOMO Entry",
    "Revenge Trade",
    "Poor Risk/Reward",
]


class InvalidJournalEntry(Exception):
    pass


def validate_journal_update(
    strategy_label: str | None, self_assessment_tags: list[str] | None
) -> None:
    """Raises InvalidJournalEntry for a value outside the canonical lists.
    None is always valid (means "leave this field unchanged" at the API
    layer). An empty list for self_assessment_tags is valid (clears it)."""
    if strategy_label is not None and strategy_label not in STRATEGY_LABELS:
        raise InvalidJournalEntry(
            f"strategy_label must be one of {STRATEGY_LABELS}, got {strategy_label!r}"
        )
    if self_assessment_tags is not None:
        unknown = [t for t in self_assessment_tags if t not in SELF_ASSESSMENT_TAGS]
        if unknown:
            raise InvalidJournalEntry(
                f"self_assessment_tags contains unknown values {unknown}, "
                f"must be a subset of {SELF_ASSESSMENT_TAGS}"
            )
