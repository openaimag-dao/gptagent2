from unittest.mock import AsyncMock

from app.config.settings import Settings
from app.services.onchain.engine import METRICS, OnChainIntelligenceEngine
from app.services.onchain.providers import DefiLlamaError


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def _engine(settings=None, defillama=None) -> OnChainIntelligenceEngine:
    engine = OnChainIntelligenceEngine(
        settings=settings or _settings(), defillama=defillama or AsyncMock()
    )
    engine._cache = AsyncMock()
    engine._cache.get.return_value = None
    return engine


async def test_unavailable_when_symbol_is_not_a_tracked_chain():
    engine = _engine()

    result = await engine.get_snapshot("AAPL")

    assert result["available"] is False
    assert "no on-chain concept" in result["reason"]
    assert set(result["metrics"]) == set(METRICS)
    assert all(v is None for v in result["metrics"].values())
    engine._defillama.get_tvl.assert_not_called()


async def test_available_when_defillama_returns_tvl():
    defillama = AsyncMock()
    defillama.get_tvl.return_value = 41_000_000_000.0
    defillama.get_stablecoin_supply.return_value = None
    defillama.get_dex_volume_24h.return_value = None

    result = await _engine(defillama=defillama).get_snapshot("ETH")

    assert result["available"] is True
    assert result["metrics"]["tvl"] == 41_000_000_000.0
    assert result["metrics"]["stablecoin_supply"] is None
    assert "DefiLlama" in result["reason"]
    assert "GLASSNODE_API_KEY" in result["reason"]


async def test_unavailable_when_defillama_calls_all_fail():
    defillama = AsyncMock()
    defillama.get_tvl.side_effect = DefiLlamaError("down")
    defillama.get_stablecoin_supply.side_effect = DefiLlamaError("down")
    defillama.get_dex_volume_24h.side_effect = DefiLlamaError("down")

    result = await _engine(defillama=defillama).get_snapshot("BTC")

    assert result["available"] is False
    assert "retrying next call" in result["reason"]


async def test_glassnode_configured_but_no_wallet_client_wired_in():
    defillama = AsyncMock()
    defillama.get_tvl.return_value = 100.0
    defillama.get_stablecoin_supply.return_value = None
    defillama.get_dex_volume_24h.return_value = None
    engine = _engine(settings=_settings(glassnode_api_key="test-key"), defillama=defillama)

    result = await engine.get_snapshot("BTC")

    assert result["available"] is True
    assert "Glassnode" in result["reason"]
    assert "wired in yet" in result["reason"]


async def test_helius_configured_only_affects_solana():
    defillama = AsyncMock()
    defillama.get_tvl.return_value = None
    defillama.get_stablecoin_supply.return_value = None
    defillama.get_dex_volume_24h.return_value = None
    engine = _engine(settings=_settings(helius_api_key="test-key"), defillama=defillama)

    btc_result = await engine.get_snapshot("BTC")
    sol_result = await engine.get_snapshot("SOL")

    assert "GLASSNODE_API_KEY" in btc_result["reason"]
    assert "Helius" in sol_result["reason"]


async def test_solana_note_only_present_for_sol():
    engine = _engine()

    btc_result = await engine.get_snapshot("BTC")
    sol_result = await engine.get_snapshot("SOL")

    assert "solana_note" not in btc_result
    assert "solana_note" in sol_result


async def test_symbol_is_uppercased():
    engine = _engine()

    result = await engine.get_snapshot("btc")

    assert result["symbol"] == "BTC"


async def test_uses_cached_defillama_metrics_without_calling_provider_again():
    defillama = AsyncMock()
    engine = _engine(defillama=defillama)
    engine._cache.get.return_value = {"tvl": 500.0, "stablecoin_supply": None, "dex_volume": None}

    result = await engine.get_snapshot("BTC")

    assert result["metrics"]["tvl"] == 500.0
    defillama.get_tvl.assert_not_called()
