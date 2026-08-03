from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api import executive_summary


async def test_404_when_engine_returns_none():
    engine = AsyncMock()
    engine.compute.return_value = None
    with patch("app.api.executive_summary.build_executive_summary_engine", return_value=engine):
        with pytest.raises(HTTPException) as exc_info:
            await executive_summary.get_executive_summary("BTC")
    assert exc_info.value.status_code == 404


async def test_returns_payload_from_engine():
    engine = AsyncMock()
    engine.compute.return_value = {"symbol": "BTC", "overall_score": 62}
    with patch("app.api.executive_summary.build_executive_summary_engine", return_value=engine):
        payload = await executive_summary.get_executive_summary("btc")
    engine.compute.assert_awaited_once_with("BTC")
    assert payload["symbol"] == "BTC"
    assert payload["overall_score"] == 62
