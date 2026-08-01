"""v5.5 Market Scanner sector taxonomy -- a static, curated map of
well-known symbols to one of the mission's 10 sectors. Deliberately not
exhaustive: classifying all ~500 tracked coins into sectors with any
accuracy needs a real taxonomy provider (e.g. CoinGecko's own `/coins/
categories`), which isn't wired in here -- unmapped symbols honestly land
in "Unclassified" rather than being guessed at. This mirrors the project's
established pattern of a hand-maintained static table for a heuristic
that's useful but not claimed to be complete (see
app.services.watchdog.engine._MACRO_CRYPTO_IMPACT for the same shape).
"""

UNCLASSIFIED = "Unclassified"

SECTOR_MAP: dict[str, str] = {
    # Layer 1
    "BTC": "Layer 1",
    "ETH": "Layer 1",
    "SOL": "Layer 1",
    "BNB": "Layer 1",
    "ADA": "Layer 1",
    "AVAX": "Layer 1",
    "DOT": "Layer 1",
    "ATOM": "Layer 1",
    "NEAR": "Layer 1",
    "ALGO": "Layer 1",
    "TON": "Layer 1",
    "TRX": "Layer 1",
    "APT": "Layer 1",
    "SUI": "Layer 1",
    "SEI": "Layer 1",
    "HBAR": "Layer 1",
    "EGLD": "Layer 1",
    "KAS": "Layer 1",
    "TIA": "Layer 1",
    "XRP": "Layer 1",
    "XLM": "Layer 1",
    "ICP": "Layer 1",
    # Layer 2
    "MATIC": "Layer 2",
    "POL": "Layer 2",
    "ARB": "Layer 2",
    "OP": "Layer 2",
    "IMX": "Layer 2",
    "STRK": "Layer 2",
    "METIS": "Layer 2",
    "MANTA": "Layer 2",
    "ZK": "Layer 2",
    "LRC": "Layer 2",
    "BOBA": "Layer 2",
    # AI
    "FET": "AI",
    "AGIX": "AI",
    "OCEAN": "AI",
    "RNDR": "AI",
    "RENDER": "AI",
    "TAO": "AI",
    "AKT": "AI",
    "WLD": "AI",
    "NMR": "AI",
    # RWA (real-world assets)
    "ONDO": "RWA",
    "POLYX": "RWA",
    "CFG": "RWA",
    "RIO": "RWA",
    "TRU": "RWA",
    "MPL": "RWA",
    # Gaming
    "AXS": "Gaming",
    "SAND": "Gaming",
    "MANA": "Gaming",
    "GALA": "Gaming",
    "ILV": "Gaming",
    "ENJ": "Gaming",
    "YGG": "Gaming",
    "GODS": "Gaming",
    "MAGIC": "Gaming",
    # Meme
    "DOGE": "Meme",
    "SHIB": "Meme",
    "PEPE": "Meme",
    "WIF": "Meme",
    "FLOKI": "Meme",
    "BONK": "Meme",
    "BOME": "Meme",
    # DeFi
    "UNI": "DeFi",
    "AAVE": "DeFi",
    "MKR": "DeFi",
    "CRV": "DeFi",
    "LDO": "DeFi",
    "SNX": "DeFi",
    "COMP": "DeFi",
    "SUSHI": "DeFi",
    "CAKE": "DeFi",
    "DYDX": "DeFi",
    "GMX": "DeFi",
    "PENDLE": "DeFi",
    # DePIN (decentralized physical infrastructure)
    "HNT": "DePIN",
    "IOTX": "DePIN",
    "FIL": "DePIN",
    "AR": "DePIN",
    "THETA": "DePIN",
    "STORJ": "DePIN",
    # Infrastructure (oracles/indexing/interop)
    "LINK": "Infrastructure",
    "GRT": "Infrastructure",
    "API3": "Infrastructure",
    "BAND": "Infrastructure",
    "AXL": "Infrastructure",
    "ZRO": "Infrastructure",
    "W": "Infrastructure",
    # Stablecoins
    "USDT": "Stablecoins",
    "USDC": "Stablecoins",
    "DAI": "Stablecoins",
    "TUSD": "Stablecoins",
    "FDUSD": "Stablecoins",
    "USDE": "Stablecoins",
}

ALL_SECTORS: tuple[str, ...] = (
    "Layer 1",
    "Layer 2",
    "AI",
    "RWA",
    "Gaming",
    "Meme",
    "DeFi",
    "DePIN",
    "Infrastructure",
    "Stablecoins",
)


def classify_sector(symbol: str) -> str:
    return SECTOR_MAP.get(symbol.upper(), UNCLASSIFIED)


def compute_sector_breadth(readings: list[dict]) -> list[dict]:
    """Pure aggregation: per-sector average 24h % change, average volume,
    coin count and top mover, from one scan cycle's readings. Each
    `reading` needs `symbol`, `sector`, `change_pct_24h`, `volume_24h`.
    Unclassified coins are excluded from sector breadth entirely (they're
    not silently folded into any of the 10 named sectors)."""
    by_sector: dict[str, list[dict]] = {}
    for reading in readings:
        sector = reading.get("sector")
        if sector is None or sector == UNCLASSIFIED:
            continue
        by_sector.setdefault(sector, []).append(reading)

    breadth = []
    for sector, coins in by_sector.items():
        changes = [c["change_pct_24h"] for c in coins if c.get("change_pct_24h") is not None]
        avg_change = sum(changes) / len(changes) if changes else None
        top_mover = (
            max(coins, key=lambda c: c.get("change_pct_24h") or float("-inf")) if changes else None
        )
        breadth.append(
            {
                "sector": sector,
                "coin_count": len(coins),
                "avg_change_pct_24h": round(avg_change, 2) if avg_change is not None else None,
                "top_mover": top_mover["symbol"] if top_mover is not None else None,
                "top_mover_change_pct_24h": (
                    top_mover.get("change_pct_24h") if top_mover is not None else None
                ),
            }
        )
    return sorted(breadth, key=lambda s: s["avg_change_pct_24h"] or 0, reverse=True)
