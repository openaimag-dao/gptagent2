from app.database.models import (
    AssetClass,
    AssetPrice,
    Correlation,
    GlobalMarketScore,
    HistoricalEvent,
    MarketRegimeSnapshot,
    NewsItem,
    PatternSignal,
    ProbabilitySnapshot,
    Report,
    ScenarioSnapshot,
    SentimentSnapshot,
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
        label = name.replace("_", " ").capitalize()
        lines.append(f"- {label} ({data['points']:+d}): {state}")
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


def format_history(symbol: str, timeframe: str, rows: list, limit: int = 10) -> str:
    if not rows:
        return f"No {symbol} history synced yet for {timeframe} -- run sync_history.py."
    lines = [f"*{symbol} history ({timeframe})*", ""]
    for row in rows[-limit:]:
        rsi = f"{float(row.rsi):.1f}" if row.rsi is not None else "n/a"
        change = f"{float(row.return_pct) * 100:+.2f}%" if row.return_pct is not None else "n/a"
        date_str = row.timestamp.date().isoformat()
        lines.append(f"{date_str}: {float(row.close):,.2f} ({change}) RSI {rsi}")
    return "\n".join(lines)


def format_events(events: list[HistoricalEvent]) -> str:
    if not events:
        return "No historical events seeded yet -- run sync_history.py --seed-events."
    lines = ["*HISTORICAL EVENTS*", ""]
    for event in events:
        symbols = ", ".join(event.symbols_affected) if event.symbols_affected else "n/a"
        lines.append(f"{event.event_date.date().isoformat()} -- {event.title} ({symbols})")
    return "\n".join(lines)


def format_probability(snapshot: ProbabilitySnapshot | None) -> str:
    if snapshot is None:
        return "Not enough synced history to compute a probability yet."
    header = (
        f"*{snapshot.symbol} PROBABILITY* "
        f"({snapshot.timeframe}, {snapshot.horizon_periods}-period)"
    )
    up_down_flat = (
        f"Up: {snapshot.prob_up_pct}% | "
        f"Down: {snapshot.prob_down_pct}% | "
        f"Flat: {snapshot.prob_flat_pct}%"
    )
    lines = [
        header,
        "",
        f"Reference RSI: {float(snapshot.reference_rsi):.1f}",
        f"Sample size: {snapshot.sample_size} similar historical episodes",
        up_down_flat,
        f"Avg forward return: {float(snapshot.avg_forward_return_pct):+.2f}%",
    ]
    return "\n".join(lines)


def format_patterns(symbol: str, patterns: list[PatternSignal]) -> str:
    if not patterns:
        return f"No patterns detected yet for {symbol}."
    lines = [f"*{symbol} PATTERNS*", ""]
    for pattern in patterns:
        date_str = pattern.timestamp.date().isoformat()
        lines.append(f"{date_str}: {pattern.pattern_name} ({pattern.direction.value})")
    return "\n".join(lines)


def format_knowledge(symbol: str, analogs: list[dict]) -> str:
    if not analogs:
        return f"No similar historical episodes found yet for {symbol}."
    lines = [f"*{symbol} SIMILAR HISTORICAL EPISODES*", ""]
    for analog in analogs:
        date_str = analog["timestamp"].date().isoformat()
        forward = analog["forward_return_pct"]
        forward_str = f"{forward:+.2f}%" if forward is not None else "n/a"
        line = f"{date_str} (RSI {analog['rsi']:.1f}): next move {forward_str}"
        if analog["nearby_events"]:
            titles = ", ".join(e["title"] for e in analog["nearby_events"])
            line += f" -- {titles}"
        lines.append(line)
    return "\n".join(lines)


def format_global_score(row: GlobalMarketScore | None) -> str:
    if row is None:
        return "Not enough data yet -- regime detection and signal scoring need to run first."
    return "\n".join(
        [
            "*GLOBAL MARKET SCORE*",
            "",
            f"Global score: {row.global_score}/100",
            f"Risk-On {row.risk_on_score} / Risk-Off {row.risk_off_score}",
            f"Liquidity: {row.liquidity_score}",
            f"Fear {row.fear_score} / Greed {row.greed_score}",
            f"Macro pressure: {row.macro_pressure_score}",
            f"Institutional activity: {row.institutional_activity_score}",
            f"Crypto strength: {row.crypto_strength_score}",
            f"Stock strength: {row.stock_strength_score}",
        ]
    )


def format_similar_periods(symbol: str, matches: list[dict], limit: int = 5) -> str:
    if not matches:
        return f"Not enough synced history for {symbol} to find similar periods yet."
    lines = [f"*{symbol} SIMILAR HISTORICAL PERIODS*", ""]
    for m in matches[:limit]:
        date_str = m["date"].date().isoformat()
        regime = m["market_regime"] or "unknown"
        forward_1d = m["forward_returns_pct"]["1d"]
        forward_30d = m["forward_returns_pct"]["30d"]
        f1 = f"{forward_1d:+.2f}%" if forward_1d is not None else "n/a"
        f30 = f"{forward_30d:+.2f}%" if forward_30d is not None else "n/a"
        lines.append(
            f"{date_str} (similarity {m['similarity']}, regime {regime}): " f"1d {f1} | 30d {f30}"
        )
    return "\n".join(lines)


def format_etf_proxy(data: dict) -> str:
    if not data.get("available"):
        return f"ETF flow proxy unavailable: {data.get('reason', 'no data')}"
    return "\n".join(
        [
            "*ETF FLOW PROXY* (news-sentiment based, not confirmed dollar flows)",
            "",
            f"Classification: {data['classification']}",
            (
                f"{data['bullish_items']} bullish / {data['bearish_items']} bearish / "
                f"{data['neutral_items']} neutral items ({data['window_hours']}h window)"
            ),
        ]
    )


def format_whale_snapshot(data: dict) -> str:
    if not data.get("available"):
        return f"Whale Intelligence unavailable: {data.get('reason', 'no data')}"
    lines = ["*WHALE ACTIVITY*", ""]
    lines.extend(f"{k}: {v}" for k, v in data.items() if k not in ("available", "symbol"))
    return "\n".join(lines)


def format_agent_outputs(outputs: dict) -> str:
    return "\n\n".join(output.summary for output in outputs.values())


def format_scenarios(row: ScenarioSnapshot | None) -> str:
    if row is None:
        return "Not enough data yet -- regime detection and signal scoring need to run first."
    lines = ["*SCENARIOS*", ""]
    for scenario in sorted(row.scenarios, key=lambda s: s["probability_pct"], reverse=True):
        lines.append(f"*{scenario['name']}* -- {scenario['probability_pct']}%")
        lines.append(scenario["rationale"])
        lines.append("")
    return "\n".join(lines).strip()


def format_sentiment(row: SentimentSnapshot) -> str:
    lines = ["*SENTIMENT*", ""]
    if row.fear_greed_value is not None:
        lines.append(
            f"Fear & Greed Index: {row.fear_greed_value}/100 ({row.fear_greed_classification})"
        )
    else:
        lines.append("Fear & Greed Index: unavailable this cycle.")
    if row.news_sentiment_score is not None:
        lines.append(f"News sentiment: {row.news_sentiment_score}/100")
    lines.append(f"Social/options sentiment: {row.social_sentiment_reason}")
    if row.global_sentiment_score is not None:
        lines.append("")
        lines.append(f"Global Sentiment Score: {row.global_sentiment_score}/100")
    return "\n".join(lines)


def format_conviction(data: dict) -> str:
    lines = ["*CONVICTION*", ""]
    signal = data.get("signal")
    if signal is None:
        lines.append("Signal: not yet computed.")
    else:
        lines.append(
            f"Signal: {signal['tier']} ({signal['effective_confidence_pct']}% effective confidence)"
        )
    probability = data.get("probability")
    if probability is None:
        lines.append("Probability: not yet computed.")
    else:
        lines.append(
            f"{probability['symbol']} probability: {probability['tier']} "
            f"({probability['effective_confidence_pct']}% effective confidence, "
            f"sample size {probability['sample_size']})"
        )
    return "\n".join(lines)


def format_liquidity(data: dict) -> str:
    return "\n".join(
        [
            "*LIQUIDITY*",
            "",
            f"Liquidity: {data['liquidity_score']}/100",
            f"Macro pressure: {data['macro_pressure_score']}/100",
            f"Risk-On {data['risk_on_score']} / Risk-Off {data['risk_off_score']}",
        ]
    )


def format_portfolio(health: dict) -> str:
    if health.get("empty"):
        return "Portfolio is empty. Add a position via POST /api/portfolio/positions."
    lines = [
        "*PORTFOLIO*",
        "",
        f"Total value: {health['total_value']:,.2f}",
        f"Health score: {health['health_score']}/100"
        if health["health_score"] is not None
        else "Health score: unavailable",
        "",
        "*Positions*",
    ]
    for p in health["positions"]:
        if not p.get("priced"):
            lines.append(f"- {p['symbol']}: {p['quantity']} (no live price)")
            continue
        pnl = f" ({p['unrealized_pnl_pct']:+.2f}%)" if p["unrealized_pnl_pct"] is not None else ""
        lines.append(
            f"- {p['symbol']}: {p['quantity']} @ {p['price']:,.2f} = {p['value']:,.2f}{pnl}"
        )
    lines.append("")
    lines.append("*Exposure*")
    for asset_class, pct in health["exposure_pct_by_class"].items():
        lines.append(f"- {asset_class}: {pct}%")
    if health.get("max_drawdown_pct") is not None:
        lines.append(f"\nMax drawdown: {health['max_drawdown_pct']}%")
    else:
        lines.append(f"\n{health.get('drawdown_note', 'Drawdown unavailable.')}")
    return "\n".join(lines)


def format_research_result(result: dict | None) -> str:
    if result is None:
        return "No usable result -- unknown event category, no recorded events, or no history."
    return "\n".join(
        [
            f"*RESEARCH: {result['target_symbol']} after {result['event_category'].upper()}* "
            f"({result['timeframe']}, {result['horizon_periods']}-period horizon)",
            "",
            f"Occurrences: {result['occurrences']}",
            f"Win rate: {result['win_rate_pct']}%",
            f"Avg return: {result['avg_return_pct']}%",
            f"Max drawdown: {result['max_drawdown_pct']}%",
            f"Profit factor: {result['profit_factor']}",
            f"Sharpe ratio: {result['sharpe_ratio']}",
        ]
    )


def format_backtest_result(result: dict | None) -> str:
    if result is None:
        return "No historical occurrences of this rule found."
    return "\n".join(
        [
            f"*BACKTEST: {result['target_symbol']}* ({result['timeframe']}, "
            f"{result['horizon_periods']}-period horizon)",
            "",
            f"Occurrences: {result['occurrences']}",
            f"Win rate: {result['win_rate_pct']}%",
            f"Avg return: {result['avg_return_pct']}%",
            f"Max drawdown: {result['max_drawdown_pct']}%",
            f"Profit factor: {result['profit_factor']}",
            f"Sharpe ratio: {result['sharpe_ratio']}",
        ]
    )
