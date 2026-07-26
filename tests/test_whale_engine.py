from unittest.mock import AsyncMock

from app.services.whales.engine import WhaleIntelligenceEngine
from app.services.whales.providers.coinalyze import CoinalyzeError
from app.services.whales.providers.coinglass import CoinGlassError


def _engine(coinglass=None, coinalyze=None) -> WhaleIntelligenceEngine:
    engine = WhaleIntelligenceEngine(
        coinglass=coinglass or AsyncMock(configured=False),
        coinalyze=coinalyze or AsyncMock(configured=False),
    )
    engine._cache = AsyncMock()
    engine._cache.get.return_value = None
    return engine


async def test_unavailable_when_neither_provider_configured():
    result = await _engine().get_snapshot("BTC")

    assert result["available"] is False
    assert "COINGLASS_API_KEY" in result["reason"]
    assert result["would_return"]


async def test_uses_coinglass_when_it_succeeds():
    coinglass = AsyncMock(configured=True)
    coinglass.get_snapshot.return_value = {"funding_rate": 0.0006, "long_short_ratio": 1.8}
    coinalyze = AsyncMock(configured=True)

    result = await _engine(coinglass=coinglass, coinalyze=coinalyze).get_snapshot("BTC")

    assert result["available"] is True
    assert result["source"] == "coinglass"
    assert result["classification"] == "long_heavy"
    coinalyze.get_snapshot.assert_not_called()


async def test_falls_back_to_coinalyze_when_coinglass_fails():
    coinglass = AsyncMock(configured=True)
    coinglass.get_snapshot.side_effect = CoinGlassError("rate limited")
    coinalyze = AsyncMock(configured=True)
    coinalyze.get_snapshot.return_value = {"funding_rate": -0.001}

    result = await _engine(coinglass=coinglass, coinalyze=coinalyze).get_snapshot("BTC")

    assert result["available"] is True
    assert result["source"] == "coinalyze"
    assert result["classification"] == "short_heavy"


async def test_unavailable_when_both_fail():
    coinglass = AsyncMock(configured=True)
    coinglass.get_snapshot.side_effect = CoinGlassError("down")
    coinalyze = AsyncMock(configured=True)
    coinalyze.get_snapshot.side_effect = CoinalyzeError("down")

    result = await _engine(coinglass=coinglass, coinalyze=coinalyze).get_snapshot("BTC")

    assert result["available"] is False


async def test_balanced_classification_when_ratio_and_funding_are_mid_range():
    coinglass = AsyncMock(configured=True)
    coinglass.get_snapshot.return_value = {"funding_rate": 0.0001, "long_short_ratio": 1.0}

    result = await _engine(coinglass=coinglass).get_snapshot("BTC")

    assert result["classification"] == "balanced"


async def test_uses_cached_result_without_calling_either_provider():
    coinglass = AsyncMock(configured=True)
    coinalyze = AsyncMock(configured=True)
    engine = _engine(coinglass=coinglass, coinalyze=coinalyze)
    engine._cache.get.return_value = {"available": True, "symbol": "BTC", "source": "coinglass"}

    result = await engine.get_snapshot("BTC")

    assert result["source"] == "coinglass"
    coinglass.get_snapshot.assert_not_called()
    coinalyze.get_snapshot.assert_not_called()
