from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api import trade_setup


async def test_rejects_unknown_horizon():
    with pytest.raises(HTTPException) as exc_info:
        await trade_setup.get_trade_setup("BTC", horizon="99h")
    assert exc_info.value.status_code == 400


async def test_404_when_no_forecast_available():
    with patch("app.api.trade_setup.evaluate_trade_setup_for_symbol", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            await trade_setup.get_trade_setup("BTC", horizon="24h")
    assert exc_info.value.status_code == 404


async def test_returns_the_setup_payload():
    setup = {
        "recommendation": "TRADE_OK",
        "reasons": [],
        "symbol": "BTC",
        "horizon": "24h",
        "side": "BUY",
    }
    with patch("app.api.trade_setup.evaluate_trade_setup_for_symbol", return_value=setup):
        result = await trade_setup.get_trade_setup("BTC", horizon="24h")
    assert result == setup
