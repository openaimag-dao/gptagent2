import pytest

from app.services.futures_sim.journal import (
    SELF_ASSESSMENT_TAGS,
    STRATEGY_LABELS,
    InvalidJournalEntry,
    validate_journal_update,
)


def test_none_values_are_always_valid():
    validate_journal_update(None, None)


def test_a_canonical_strategy_label_is_valid():
    for label in STRATEGY_LABELS:
        validate_journal_update(label, None)


def test_an_unknown_strategy_label_is_rejected():
    with pytest.raises(InvalidJournalEntry):
        validate_journal_update("NotARealLabel", None)


def test_an_empty_tag_list_is_valid_and_clears_tags():
    validate_journal_update(None, [])


def test_canonical_tags_are_valid():
    validate_journal_update(None, list(SELF_ASSESSMENT_TAGS))


def test_a_single_unknown_tag_is_rejected():
    with pytest.raises(InvalidJournalEntry):
        validate_journal_update(None, ["Good Entry", "NotARealTag"])
