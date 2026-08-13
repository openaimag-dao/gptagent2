from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api import no_trade


async def test_rejects_unknown_horizon():
    with pytest.raises(HTTPException) as exc_info:
        await no_trade.get_no_trade_verdict("BTC", horizon="99h")
    assert exc_info.value.status_code == 400


async def test_404_when_no_forecast_available():
    with patch("app.api.no_trade.evaluate_no_trade_for_symbol", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            await no_trade.get_no_trade_verdict("BTC", horizon="24h")
    assert exc_info.value.status_code == 404


async def test_returns_the_verdict_payload():
    verdict = {"recommendation": "TRADE_OK", "reasons": [], "symbol": "BTC", "horizon": "24h"}
    with patch("app.api.no_trade.evaluate_no_trade_for_symbol", return_value=verdict):
        result = await no_trade.get_no_trade_verdict("BTC", horizon="24h")
    assert result == verdict
