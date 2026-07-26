import pytest

from app.services.memory.engine import CATEGORY_NAMES, MemoryEngine


def test_category_names_cover_every_persisted_history_table():
    expected = {
        "predictions",
        "signals",
        "regime",
        "correlations",
        "patterns",
        "similarity",
        "knowledge_rules",
        "whale",
        "etf",
        "sentiment",
        "global_score",
        "news",
        "macro_events",
        "alerts",
    }
    assert set(CATEGORY_NAMES) == expected


@pytest.mark.asyncio
async def test_get_category_rejects_unknown_category_without_touching_db():
    engine = MemoryEngine(session_factory=None)
    with pytest.raises(ValueError, match="Unknown memory category"):
        await engine.get_category("not_a_real_category")
