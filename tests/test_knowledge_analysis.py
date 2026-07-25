from datetime import UTC, datetime, timedelta

from app.services.knowledge.analysis import find_similar_episodes


def _timestamps(n: int) -> list[datetime]:
    base = datetime(2020, 1, 1, tzinfo=UTC)
    return [base + timedelta(days=i) for i in range(n)]


def test_find_similar_episodes_returns_closest_by_rsi():
    # RSI 30 at index 0 should be the closest match to a current RSI of 32.
    rsi_series = [30.0, 70.0, 50.0, 90.0, 20.0]
    volatility_series = [0.01, 0.01, 0.01, 0.01, 0.01]
    timestamps = _timestamps(5)

    episodes = find_similar_episodes(
        rsi_series, volatility_series, timestamps, current_rsi=32.0, current_volatility=0.01,
        k=1, exclude_recent=0,
    )

    assert len(episodes) == 1
    assert episodes[0]["timestamp"] == timestamps[0]


def test_find_similar_episodes_excludes_recent_candles():
    rsi_series = [30.0 + i for i in range(10)]
    volatility_series = [0.01] * 10
    timestamps = _timestamps(10)

    episodes = find_similar_episodes(
        rsi_series, volatility_series, timestamps, current_rsi=50.0, current_volatility=0.01,
        k=10, exclude_recent=3,
    )

    assert len(episodes) == 7
    excluded_timestamps = set(timestamps[-3:])
    assert all(ep["timestamp"] not in excluded_timestamps for ep in episodes)


def test_find_similar_episodes_respects_k():
    rsi_series = [30.0 + i for i in range(20)]  # varies so z-scoring is well-defined
    volatility_series = [0.01] * 20
    timestamps = _timestamps(20)

    episodes = find_similar_episodes(
        rsi_series, volatility_series, timestamps, current_rsi=50.0, current_volatility=0.01,
        k=3, exclude_recent=0,
    )

    assert len(episodes) == 3


def test_find_similar_episodes_handles_flat_rsi_series():
    # No variance in RSI -- std is 0, function should not divide by zero.
    rsi_series = [50.0] * 5
    volatility_series = [0.01] * 5
    timestamps = _timestamps(5)

    episodes = find_similar_episodes(
        rsi_series, volatility_series, timestamps, current_rsi=50.0, current_volatility=0.01,
    )

    assert episodes == []


def test_find_similar_episodes_falls_back_to_rsi_only_without_volatility():
    rsi_series = [30.0, 70.0, 50.0]
    volatility_series = [None, None, None]
    timestamps = _timestamps(3)

    episodes = find_similar_episodes(
        rsi_series, volatility_series, timestamps, current_rsi=32.0, current_volatility=None,
        k=1, exclude_recent=0,
    )

    assert len(episodes) == 1
    assert episodes[0]["timestamp"] == timestamps[0]
