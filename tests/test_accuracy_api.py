from unittest.mock import AsyncMock, patch

from app.api import accuracy


async def test_get_accuracy_delegates_to_engine():
    engine = AsyncMock()
    engine.compute.return_value = {"overall": {"evaluated_count": 5}}
    with patch("app.api.accuracy.build_accuracy_engine", return_value=engine):
        result = await accuracy.get_accuracy(symbol=None)
    engine.compute.assert_awaited_once_with(None)
    assert result["overall"]["evaluated_count"] == 5


async def test_get_accuracy_passes_symbol_filter():
    engine = AsyncMock()
    engine.compute.return_value = {"symbol": "BTC"}
    with patch("app.api.accuracy.build_accuracy_engine", return_value=engine):
        result = await accuracy.get_accuracy(symbol="btc")
    engine.compute.assert_awaited_once_with("btc")
    assert result["symbol"] == "BTC"
