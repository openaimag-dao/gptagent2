from datetime import UTC, datetime

from app.services.knowledge.engine import build_grounding_text


def _match(rsi=72.5, forward_7d=3.2, nearby_events=None, date=datetime(2025, 6, 1, tzinfo=UTC)):
    return {
        "date": date,
        "rsi": rsi,
        "forward_returns_pct": {"7d": forward_7d},
        "nearby_events": nearby_events or [],
    }


def test_build_grounding_text_no_matches():
    text = build_grounding_text("BTC", [])
    assert "No sufficiently similar historical episode" in text
    assert "BTC" in text


def test_build_grounding_text_formats_matches():
    matches = [_match()]
    text = build_grounding_text("BTC", matches)
    assert "2025-06-01" in text
    assert "RSI 72.5" in text
    assert "+3.20%" in text


def test_build_grounding_text_handles_missing_forward_return():
    matches = [_match(forward_7d=None)]
    text = build_grounding_text("BTC", matches)
    assert "n/a" in text


def test_build_grounding_text_includes_nearby_events():
    matches = [_match(nearby_events=[{"title": "Fed rate decision", "event_date": "2025-06-02"}])]
    text = build_grounding_text("BTC", matches)
    assert "Fed rate decision" in text
