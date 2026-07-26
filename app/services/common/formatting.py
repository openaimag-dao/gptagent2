"""Shared pure formatting helpers for turning live AssetPrice rows into
human-readable lines -- used by the AI Brain prompt builder and every
multi-agent summarizer so the same "- SYMBOL: price (change% 24h)" shape
is defined once."""

from app.database.models import AssetPrice


def format_asset_lines(assets: list[AssetPrice], symbols: tuple[str, ...]) -> list[str]:
    by_symbol = {a.symbol: a for a in assets}
    lines = []
    for symbol in symbols:
        asset = by_symbol.get(symbol)
        if asset is None:
            lines.append(f"- {symbol}: not available")
            continue
        change = f"{asset.change_pct_24h:+.2f}%" if asset.change_pct_24h is not None else "n/a"
        lines.append(f"- {symbol}: {float(asset.price):,.2f} ({change} 24h)")
    return lines


def asset_change_dict(assets: list[AssetPrice], symbols: tuple[str, ...]) -> dict:
    """Same lookup as `format_asset_lines`, as a JSON-friendly dict instead
    of Markdown lines -- used by the multi-agent `data` payloads."""
    by_symbol = {a.symbol: a for a in assets}
    result: dict = {}
    for symbol in symbols:
        asset = by_symbol.get(symbol)
        if asset is None:
            result[symbol] = None
            continue
        result[symbol] = {
            "price": float(asset.price),
            "change_pct_24h": (
                float(asset.change_pct_24h) if asset.change_pct_24h is not None else None
            ),
        }
    return result
