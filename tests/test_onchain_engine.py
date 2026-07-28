from app.config.settings import Settings
from app.services.onchain.engine import METRICS, OnChainIntelligenceEngine


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


async def test_unavailable_when_no_provider_configured():
    engine = OnChainIntelligenceEngine(settings=_settings())

    result = await engine.get_snapshot("BTC")

    assert result["available"] is False
    assert "No on-chain data provider configured" in result["reason"]
    assert set(result["metrics"]) == set(METRICS)
    assert all(v is None for v in result["metrics"].values())


async def test_glassnode_configured_but_no_client_wired_in():
    engine = OnChainIntelligenceEngine(settings=_settings(glassnode_api_key="test-key"))

    result = await engine.get_snapshot("BTC")

    assert result["available"] is False
    assert "Glassnode" in result["reason"]
    assert "not implemented" in result["reason"]


async def test_helius_configured_only_affects_solana():
    engine = OnChainIntelligenceEngine(settings=_settings(helius_api_key="test-key"))

    btc_result = await engine.get_snapshot("BTC")
    sol_result = await engine.get_snapshot("SOL")

    assert "No on-chain data provider configured" in btc_result["reason"]
    assert "Helius" in sol_result["reason"]


async def test_solana_note_only_present_for_sol():
    engine = OnChainIntelligenceEngine(settings=_settings())

    btc_result = await engine.get_snapshot("BTC")
    sol_result = await engine.get_snapshot("SOL")

    assert "solana_note" not in btc_result
    assert "solana_note" in sol_result


async def test_symbol_is_uppercased():
    engine = OnChainIntelligenceEngine(settings=_settings())

    result = await engine.get_snapshot("btc")

    assert result["symbol"] == "BTC"
