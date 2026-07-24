from app.database.models import (
    AssetClass,
    AssetPrice,
    Correlation,
    MarketRegimeSnapshot,
    NewsItem,
    Report,
    SignalSnapshot,
)

_CLASS_LABELS: dict[AssetClass, str] = {
    AssetClass.CRYPTO: "Crypto",
    AssetClass.INDEX: "Indices",
    AssetClass.STOCK: "Stocks",
    AssetClass.MACRO: "Macro",
}

_CLASS_ORDER: tuple[AssetClass, ...] = (
    AssetClass.CRYPTO,
    AssetClass.INDEX,
    AssetClass.STOCK,
    AssetClass.MACRO,
)


def _price_line(asset: AssetPrice) -> str:
    change = f"{asset.change_pct_24h:+.2f}%" if asset.change_pct_24h is not None else "n/a"
    return f"{asset.symbol}: {float(asset.price):,.2f} ({change} 24h)"


def format_market_summary(assets: list[AssetPrice]) -> str:
    if not assets:
        return "No market data collected yet -- check back shortly."

    by_class: dict[AssetClass, list[AssetPrice]] = {}
    for asset in assets:
        by_class.setdefault(asset.asset_class, []).append(asset)

    lines = ["*MARKET SUMMARY*", ""]
    for asset_class in _CLASS_ORDER:
        items = by_class.get(asset_class)
        if not items:
            continue
        lines.append(f"*{_CLASS_LABELS[asset_class]}*")
        lines.extend(_price_line(a) for a in sorted(items, key=lambda a: a.symbol))
        lines.append("")
    return "\n".join(lines).strip()


def format_asset_class(assets: list[AssetPrice], asset_class: AssetClass, title: str) -> str:
    items = [a for a in assets if a.asset_class == asset_class]
    if not items:
        return f"No {title.lower()} data collected yet -- check back shortly."
    lines = [f"*{title}*", ""]
    lines.extend(_price_line(a) for a in sorted(items, key=lambda a: a.symbol))
    return "\n".join(lines)


def format_single_asset(symbol: str, asset: AssetPrice | None) -> str:
    if asset is None:
        return f"No data available yet for {symbol.upper()}."

    change = f"{asset.change_pct_24h:+.2f}%" if asset.change_pct_24h is not None else "n/a"
    lines = [
        f"*{asset.name} ({asset.symbol})*",
        f"Price: {float(asset.price):,.2f}",
        f"24h change: {change}",
    ]
    if asset.market_cap is not None:
        lines.append(f"Market cap: {float(asset.market_cap):,.0f}")
    if asset.volume_24h is not None:
        lines.append(f"24h volume: {float(asset.volume_24h):,.0f}")
    return "\n".join(lines)


def format_news(items: list[NewsItem], limit: int = 8) -> str:
    if not items:
        return "No news collected yet -- check back shortly."
    lines = ["*LATEST NEWS*", ""]
    for item in items[:limit]:
        lines.append(f"[{item.category.value}] ({item.sentiment.value}) {item.title}")
        lines.append(item.url)
        lines.append("")
    return "\n".join(lines).strip()


def format_signal(snapshot: SignalSnapshot | None) -> str:
    if snapshot is None:
        return "No signal has been computed yet -- check back shortly."
    lines = [
        "*BULL/BEAR SIGNAL*",
        "",
        f"Bull score: {snapshot.bull_score}",
        f"Bear score: {snapshot.bear_score}",
        f"Net score: {snapshot.net_score}",
        f"Confidence: {snapshot.confidence_pct}%",
        "",
        "*Factors*",
    ]
    for name, data in snapshot.factors.items():
        if data["triggered"] is True:
            state = "triggered"
        elif data["triggered"] is False:
            state = "not triggered"
        else:
            state = "no data"
        lines.append(f"- {name} ({data['points']:+d}): {state}")
    return "\n".join(lines)


def format_regime(snapshot: MarketRegimeSnapshot | None) -> str:
    if snapshot is None:
        return "No regime has been detected yet -- check back shortly."
    return f"*MARKET REGIME*\n\n{snapshot.regime.value.replace('_', ' ').title()}"


def format_correlations(correlations: list[Correlation]) -> str:
    if not correlations:
        return "No correlation data available yet -- check back shortly."
    lines = ["*CORRELATIONS*", ""]
    for c in correlations:
        lines.append(f"{c.symbol_a}/{c.symbol_b} ({c.window_days}d): {float(c.correlation):+.2f}")
    return "\n".join(lines)


def format_report(report: Report | None) -> str:
    if report is None:
        return (
            "No AI report has been generated yet. Generate one with /report once market "
            "data, regime detection and signals have run at least once."
        )

    analysis = report.analysis
    lines = [
        "*AI MARKET ANALYSIS*",
        "",
        f"Market Regime: {report.regime.replace('_', ' ').title()}",
        f"Risk Level: {report.risk_level.title()}",
        f"Bull Score: {report.bull_score} | Bear Score: {report.bear_score}",
        f"Confidence: {report.confidence_pct}%",
        "",
        "*What Changed*",
        analysis.get("what_changed", "n/a"),
        "",
        "*Why*",
        analysis.get("why", "n/a"),
        "",
        "*Who Is Driving The Market*",
        analysis.get("who_is_driving", "n/a"),
        "",
        "*Institutional Interpretation*",
        analysis.get("institutional_behavior", "n/a"),
        "",
        "*Macro Explanation*",
        analysis.get("macro_explanation", "n/a"),
        "",
        "*Historical Comparison*",
        analysis.get("historical_comparison", "n/a"),
        "",
        "*Trading Risks*",
        analysis.get("main_risks", "n/a"),
        "",
        "*Key Events Today*",
        analysis.get("key_events_today", "n/a"),
        "",
        "*Today's Probability*",
        (
            f"Bullish {analysis.get('probability_bullish_pct', 0)}% | "
            f"Bearish {analysis.get('probability_bearish_pct', 0)}% | "
            f"Neutral {analysis.get('probability_neutral_pct', 0)}%"
        ),
        "",
        f"_Generated at {report.generated_at.isoformat()}_",
    ]
    return "\n".join(lines)
