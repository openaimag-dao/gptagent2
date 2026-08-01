from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.services.technical.engine import TechnicalAnalysisEngine
from app.services.technical.normalizer import NormalizedIndicators


def _session_factory(session):
    session.add = MagicMock()
    session.__aenter__.return_value = session
    return MagicMock(return_value=session)


def _reading(**overrides) -> NormalizedIndicators:
    defaults = dict(
        symbol="BTC",
        timeframe="1d",
        source="local",
        price=100.0,
        rsi=25.0,
        macd_line=1.0,
        macd_signal=0.0,
        macd_histogram=1.0,
        ema_20=95.0,
        sma_20=95.0,
        sma_50=90.0,
        sma_200=85.0,
        vwma_20=95.0,
        atr=2.0,
        adx=30.0,
        cci=50.0,
        momentum=5.0,
        roc=3.0,
        stochastic_rsi=20.0,
        bollinger_upper=110.0,
        bollinger_middle=100.0,
        bollinger_lower=90.0,
        pivot_points=None,
        support=90.0,
        resistance=110.0,
        computed_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return NormalizedIndicators(**defaults)


def _engine(session=None, provider=None):
    session = session or AsyncMock()
    session_factory = _session_factory(session)
    provider = provider or AsyncMock()
    return TechnicalAnalysisEngine(session_factory, provider), session, provider


async def test_analyze_none_when_no_timeframe_data_available():
    provider = AsyncMock()
    provider.get_multi_timeframe.return_value = {"1h": None, "4h": None, "1d": None, "1w": None}
    provider.get_daily_pair.return_value = (None, None)
    engine, session, _ = _engine(provider=provider)

    result = await engine.analyze("BTC")

    assert result is None
    session.add.assert_not_called()


async def test_analyze_persists_and_returns_combined_result():
    provider = AsyncMock()
    reading = _reading()
    provider.get_multi_timeframe.return_value = {
        "1h": reading,
        "4h": reading,
        "1d": reading,
        "1w": None,
    }
    provider.get_daily_pair.return_value = (reading, _reading(rsi=50.0, macd_line=-1.0))
    session = AsyncMock()
    session.scalar.return_value = None  # no previous snapshot
    engine, session, provider = _engine(session=session, provider=provider)

    result = await engine.analyze("BTC")

    assert result is not None
    assert result["symbol"] == "BTC"
    assert result["source"] == "local"
    assert result["bullish_score"] is not None
    assert "RSIOversold" in result["active_signals"]
    session.add.assert_called_once()


async def test_analyze_detects_high_confidence_alignment():
    provider = AsyncMock()
    # Oversold RSI + support held -- 2 aligned bullish reasons.
    current = _reading(rsi=25.0, price=100.0, support=90.0)
    previous = _reading(rsi=50.0, macd_line=-1.0, macd_signal=0.0)
    provider.get_multi_timeframe.return_value = {
        "1h": current,
        "4h": current,
        "1d": current,
        "1w": None,
    }
    provider.get_daily_pair.return_value = (current, previous)
    session = AsyncMock()
    session.scalar.return_value = None
    engine, session, provider = _engine(session=session, provider=provider)

    result = await engine.analyze("BTC")

    assert result["high_confidence_alignment"] is not None
    assert result["high_confidence_alignment"]["signal"] == "HIGH_CONFIDENCE_BUY"


async def test_analyze_uses_uppercased_symbol():
    provider = AsyncMock()
    reading = _reading()
    provider.get_multi_timeframe.return_value = {"1d": reading}
    provider.get_daily_pair.return_value = (reading, None)
    session = AsyncMock()
    session.scalar.return_value = None
    engine, session, provider = _engine(session=session, provider=provider)

    result = await engine.analyze("btc")

    assert result["symbol"] == "BTC"
    provider.get_multi_timeframe.assert_awaited_once()
    args, _ = provider.get_multi_timeframe.call_args
    assert args[0] == "BTC"


async def test_get_latest_queries_by_uppercased_symbol():
    session = AsyncMock()
    session.scalar.return_value = "row"
    engine, session, _ = _engine(session=session)

    result = await engine.get_latest("btc")

    assert result == "row"
