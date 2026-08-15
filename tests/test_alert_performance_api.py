from unittest.mock import patch

from app.api import alert_performance


async def test_get_alert_performance_passes_through_alert_type_filter():
    summary = {"alert_type": "scanner:price_event", "graded_count": 5}
    with patch(
        "app.api.alert_performance.summarize_alert_performance", return_value=summary
    ) as mock_summarize:
        result = await alert_performance.get_alert_performance(alert_type="scanner:price_event")
    mock_summarize.assert_awaited_once()
    assert mock_summarize.call_args.kwargs["alert_type"] == "scanner:price_event"
    assert result == summary


async def test_get_alert_performance_defaults_to_no_filter():
    summary = {"alert_type": None, "graded_count": 0}
    with patch("app.api.alert_performance.summarize_alert_performance", return_value=summary):
        result = await alert_performance.get_alert_performance()
    assert result == summary


async def test_get_alert_performance_by_type_returns_list():
    rows = [{"alert_type": "scanner:price_event", "graded_count": 5}]
    with patch("app.api.alert_performance.summarize_alert_performance_by_type", return_value=rows):
        result = await alert_performance.get_alert_performance_by_type()
    assert result == rows
