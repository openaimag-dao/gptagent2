"""Shared pure formatting helpers for turning live AssetPrice rows into
human-readable lines -- used by the AI Brain prompt builder and every
multi-agent summarizer so the same "- SYMBOL: price (change% 24h)" shape
is defined once."""

from app.database.models import AssetPrice

_EVIDENCE_EXCERPT_LENGTH = 200


def agent_evidence_excerpt(summary: str, max_length: int = _EVIDENCE_EXCERPT_LENGTH) -> str:
    """First substantive line of an agent's summary -- skips the leading
    "*AGENT SUMMARY*" markdown header every agent starts with (see
    app/services/agents/*.py), so a quoted "evidence" excerpt is the
    agent's actual reasoning, not its section title. Shared by
    CommitteeEngine (supporting/opposing evidence) and ConsensusEngine
    (per-agent evidence behind the agree/disagree split) so both read the
    same real text instead of each re-deriving their own excerpt."""
    lines = [line.strip() for line in summary.strip().split("\n")]
    content_lines = [
        line for line in lines if line and not (line.startswith("*") and line.endswith("*"))
    ]
    text = content_lines[0] if content_lines else (lines[0] if lines else "")
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "..."


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
