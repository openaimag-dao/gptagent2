from app.services.scanner.breadth import compute_market_breadth


def _reading(symbol, change_pct_24h, volume_change_pct=None, price=100.0):
    return {
        "symbol": symbol,
        "price": price,
        "change_pct_24h": change_pct_24h,
        "volume_change_pct": volume_change_pct,
    }


def test_compute_market_breadth_counts_rising_falling_unchanged():
    readings = [
        _reading("A", 5.0),
        _reading("B", -3.0),
        _reading("C", 0.0),
        _reading("D", None),
    ]
    breadth = compute_market_breadth(readings)
    assert breadth["total_scanned"] == 4
    assert breadth["rising_count"] == 1
    assert breadth["falling_count"] == 1
    assert breadth["unchanged_count"] == 2


def test_compute_market_breadth_top_gainers_and_losers():
    readings = [_reading(f"SYM{i}", float(i)) for i in range(-5, 6)]
    breadth = compute_market_breadth(readings, top_n=3)
    assert [r["symbol"] for r in breadth["top_gainers"]] == ["SYM5", "SYM4", "SYM3"]
    assert [r["symbol"] for r in breadth["top_losers"]] == ["SYM-5", "SYM-4", "SYM-3"]


def test_compute_market_breadth_top_volume_increase():
    readings = [
        _reading("A", 1.0, volume_change_pct=200.0),
        _reading("B", 1.0, volume_change_pct=50.0),
        _reading("C", 1.0, volume_change_pct=None),
    ]
    breadth = compute_market_breadth(readings, top_n=2)
    assert [r["symbol"] for r in breadth["top_volume_increase"]] == ["A", "B"]


def test_compute_market_breadth_empty():
    breadth = compute_market_breadth([])
    assert breadth["total_scanned"] == 0
    assert breadth["top_gainers"] == []
    assert breadth["top_losers"] == []
