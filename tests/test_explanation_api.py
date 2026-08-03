from unittest.mock import AsyncMock, patch

from app.api import explanation


async def test_get_explanation_delegates_to_explainability_engine():
    engine = AsyncMock()
    engine.build.return_value = {"symbol": "BTC", "engine_breakdown": []}
    with patch("app.api.explanation.build_explainability_engine", return_value=engine):
        result = await explanation.get_explanation("btc")
    engine.build.assert_awaited_once_with("btc")
    assert result["symbol"] == "BTC"
