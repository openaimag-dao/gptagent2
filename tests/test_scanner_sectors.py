from app.services.scanner.sectors import UNCLASSIFIED, classify_sector, compute_sector_breadth


def test_classify_sector_known_and_unknown():
    assert classify_sector("BTC") == "Layer 1"
    assert classify_sector("fet") == "AI"
    assert classify_sector("NOT_A_REAL_COIN") == UNCLASSIFIED


def _reading(symbol, sector, change_pct_24h):
    return {"symbol": symbol, "sector": sector, "change_pct_24h": change_pct_24h, "volume_24h": 1.0}


def test_compute_sector_breadth_excludes_unclassified():
    readings = [
        _reading("BTC", "Layer 1", 5.0),
        _reading("ETH", "Layer 1", 3.0),
        _reading("XYZ", UNCLASSIFIED, 50.0),
    ]
    breadth = compute_sector_breadth(readings)
    assert len(breadth) == 1
    assert breadth[0]["sector"] == "Layer 1"
    assert breadth[0]["coin_count"] == 2
    assert breadth[0]["avg_change_pct_24h"] == 4.0
    assert breadth[0]["top_mover"] == "BTC"


def test_compute_sector_breadth_sorted_by_avg_change_desc():
    readings = [
        _reading("UNI", "DeFi", -2.0),
        _reading("BTC", "Layer 1", 8.0),
    ]
    breadth = compute_sector_breadth(readings)
    assert [b["sector"] for b in breadth] == ["Layer 1", "DeFi"]


def test_compute_sector_breadth_empty():
    assert compute_sector_breadth([]) == []
