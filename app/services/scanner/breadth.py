"""Pure market-breadth aggregation for the v5.5 Market Scanner -- how many
coins are rising/falling, top gainers/losers, top volume increase. One
scan cycle's readings in, a summary dict out; no I/O.
"""


def _slim(reading: dict, include_volume_change: bool = False) -> dict:
    slim = {
        "symbol": reading["symbol"],
        "price": reading.get("price"),
        "change_pct_24h": reading.get("change_pct_24h"),
    }
    if include_volume_change:
        slim["volume_change_pct"] = reading.get("volume_change_pct")
    return slim


def compute_market_breadth(readings: list[dict], top_n: int = 20) -> dict:
    """`readings` needs `symbol`, `price`, `change_pct_24h`, and
    (optionally) `volume_change_pct` per coin."""
    rising = [r for r in readings if (r.get("change_pct_24h") or 0) > 0]
    falling = [r for r in readings if (r.get("change_pct_24h") or 0) < 0]
    unchanged = len(readings) - len(rising) - len(falling)

    ranked_by_change = sorted(
        (r for r in readings if r.get("change_pct_24h") is not None),
        key=lambda r: r["change_pct_24h"],
    )
    top_gainers = list(reversed(ranked_by_change[-top_n:])) if ranked_by_change else []
    top_losers = ranked_by_change[:top_n]

    ranked_by_volume_change = sorted(
        (r for r in readings if r.get("volume_change_pct") is not None),
        key=lambda r: r["volume_change_pct"],
        reverse=True,
    )
    top_volume_increase = ranked_by_volume_change[:top_n]

    return {
        "total_scanned": len(readings),
        "rising_count": len(rising),
        "falling_count": len(falling),
        "unchanged_count": unchanged,
        "top_gainers": [_slim(r) for r in top_gainers],
        "top_losers": [_slim(r) for r in top_losers],
        "top_volume_increase": [_slim(r, include_volume_change=True) for r in top_volume_increase],
    }
