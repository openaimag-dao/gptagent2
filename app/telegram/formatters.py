from app.database.models import (
    AssetClass,
    AssetPrice,
    BreakoutEvent,
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
from app.services.consensus.engine import ConsensusResult

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


def format_learning(result: dict | None, symbol: str, timeframe: str) -> str:
    if result is None:
        return (
            f"No graded predictions yet for {symbol}/{timeframe} -- a prediction only "
            "counts once its horizon has actually elapsed in the stored history."
        )
    lines = [
        f"*{result['symbol']} SELF-LEARNING ACCURACY* ({result['timeframe']})",
        "",
        f"Evaluated predictions: {result['evaluated_predictions']}",
        f"Accuracy: {result['accuracy_pct']}%",
        "",
        "*Recent*",
    ]
    for entry in result["recent"]:
        mark = "correct" if entry["correct"] else "wrong"
        lines.append(
            f"{entry['reference_timestamp'].date().isoformat()}: predicted "
            f"{entry['predicted']}, realized {entry['realized']} "
            f"({entry['realized_return_pct']:+.2f}%) -- {mark}"
        )
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


def format_breakout(symbol: str, event: BreakoutEvent | None) -> str:
    if event is None:
        return f"No breakout/breakdown detected yet for {symbol}."
    lines = [
        f"*{symbol} BREAKOUT INTELLIGENCE* ({event.timeframe})",
        "",
        (
            f"{event.event_type.replace('_', ' ').title()} ({event.direction}) at level "
            f"{float(event.level):.4f}, price {float(event.price):.4f}"
        ),
        (
            f"Probability: {event.probability_pct}%"
            if event.probability_pct is not None
            else "Probability: unavailable"
        )
        + f" | Confidence: {event.confidence_pct}%",
    ]
    if event.risk_score is not None:
        lines.append(f"Risk score: {event.risk_score}/100")
    lines.append(f"Expected: {event.expected_continuation}")
    lines.append("")
    lines.append(event.reasoning)
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
    lines = [
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
        (
            f"Trend strength: {row.trend_strength_score}"
            if row.trend_strength_score is not None
            else "Trend strength: unavailable"
        ),
        f"Risk score: {row.risk_score}"
        if row.risk_score is not None
        else "Risk score: unavailable",
        (
            f"Confidence score: {row.confidence_score}"
            if row.confidence_score is not None
            else "Confidence score: unavailable"
        ),
    ]
    return "\n".join(lines)


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


def format_onchain(snapshot: dict) -> str:
    lines = [f"*{snapshot['symbol']} ON-CHAIN INTELLIGENCE*", "", snapshot["reason"]]
    if snapshot.get("solana_note"):
        lines.append("")
        lines.append(snapshot["solana_note"])
    lines.append("")
    lines.append("Tracked metrics (all unavailable): " + ", ".join(snapshot["metrics"]))
    return "\n".join(lines)


def format_agent_outputs(outputs: dict) -> str:
    return "\n\n".join(output.summary for output in outputs.values())


def format_consensus(result: ConsensusResult | None) -> str:
    if result is None:
        return "No agent reported a direction this cycle -- nothing to tally yet."
    lines = [
        "*CONSENSUS*",
        "",
        f"Bullish {result.bullish_pct}% | Bearish {result.bearish_pct}% | "
        f"Neutral {result.neutral_pct}%",
        f"Agreement: {result.agreement_score}% | Conflict: {result.conflict_pct}%",
        "",
    ]
    if result.bullish_agents:
        lines.append(f"Bullish: {', '.join(result.bullish_agents)}")
    if result.bearish_agents:
        lines.append(f"Bearish: {', '.join(result.bearish_agents)}")
    if result.neutral_agents:
        lines.append(f"Neutral: {', '.join(result.neutral_agents)}")
    if result.unavailable_agents:
        lines.append(f"No data this cycle: {', '.join(result.unavailable_agents)}")
    return "\n".join(lines)


def format_committee(verdict: dict | None) -> str:
    if verdict is None:
        return "No agent reported a direction this cycle -- the committee has nothing to vote on."
    lines = [
        "*AI INVESTMENT COMMITTEE*",
        "",
        f"Final recommendation: {verdict['final_recommendation']}",
        (
            f"Majority: {verdict['majority_decision']} ({verdict['majority_pct']}%) | "
            f"Dissent: {verdict['dissent_pct']}% | Confidence: {verdict['confidence_pct']}%"
        ),
        "",
        verdict["reasoning"],
    ]
    if verdict["supporting_evidence"]:
        lines.append("")
        lines.append("Supporting evidence:")
        lines.extend(f"- {e['agent']}: {e['evidence']}" for e in verdict["supporting_evidence"])
    if verdict["opposing_evidence"]:
        lines.append("")
        lines.append("Opposing evidence (minority):")
        lines.extend(f"- {e['agent']}: {e['evidence']}" for e in verdict["opposing_evidence"])
    return "\n".join(lines)


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


def format_explanation(data: dict) -> str:
    lines = [f"*WHY -- {data['symbol']}*", ""]

    if data["indicators"]:
        lines.append("*Triggered indicators*")
        for ind in data["indicators"]:
            lines.append(f"- {ind['name'].replace('_', ' ')} ({ind['points']:+d})")
        lines.append("")

    if data["macro_drivers"]:
        lines.append("*Macro drivers*")
        for name, value in data["macro_drivers"].items():
            lines.append(f"- {name.replace('_', ' ')}: {value}")
        lines.append("")

    if data["supporting_news"]:
        lines.append("*Supporting news*")
        for item in data["supporting_news"]:
            lines.append(f"- [{item['sentiment']}] {item['title']}")
        lines.append("")

    if data["historical_examples"]:
        lines.append("*Historical examples*")
        for ex in data["historical_examples"]:
            forward = (
                f"{ex['forward_return_7d_pct']:+.2f}%"
                if ex["forward_return_7d_pct"] is not None
                else "n/a"
            )
            lines.append(
                f"- {ex['match_timestamp'][:10]} ({ex['similarity_score']:.0f}% similar, "
                f"{ex['regime'] or 'regime unknown'}): 7d forward {forward}"
            )
        lines.append("")

    if data["risk_factors"]:
        rf = data["risk_factors"]
        lines.append("*Risk factors*")
        lines.append(
            f"Fear {rf['fear_score']} | Macro pressure {rf['macro_pressure_score']} | "
            f"Risk-off {rf['risk_off_score']}"
        )
        lines.append("")

    if data["alternative_view"]:
        av = data["alternative_view"]
        lines.append("*Alternative view*")
        lines.append(f"{av['name']} ({av['probability_pct']}%): {av['rationale']}")

    if len(lines) <= 2:
        lines.append("Not enough data computed yet to explain this read.")

    return "\n".join(lines).strip()


def format_status(snapshots: dict) -> str:
    lines = ["*SYSTEM STATUS*", ""]
    for label, timestamp in snapshots.items():
        value = timestamp.isoformat() if timestamp is not None else "never computed"
        lines.append(f"{label}: {value}")
    return "\n".join(lines)


def format_risk(data: dict) -> str:
    lines = ["*RISK*", ""]
    if data["global_score"] is not None:
        gs = data["global_score"]
        lines.append(f"Risk-off: {gs['risk_off_score']}/100 | Risk-on: {gs['risk_on_score']}/100")
        lines.append(
            f"Fear: {gs['fear_score']}/100 | Macro pressure: {gs['macro_pressure_score']}/100"
        )
    else:
        lines.append("Global Score not computed yet -- run /score first.")
    lines.append("")
    if data["signal_conviction"] is not None:
        sc = data["signal_conviction"]
        lines.append(f"Signal conviction: {sc['tier']} ({sc['effective_confidence_pct']}%)")
    else:
        lines.append("Signal conviction: unavailable -- no signal computed yet.")
    return "\n".join(lines)


def format_watchdog(entries: list[dict]) -> str:
    if not entries:
        return "*MARKET WATCHDOG*\n\nNo detections logged yet."
    lines = ["*MARKET WATCHDOG*", ""]
    for entry in entries:
        s = entry["summary"]
        state = "sent" if s["broadcast"] else "suppressed (gated/cooldown)"
        lines.append(
            f"{entry['timestamp'][:16]} [{s['alert_type']}] {s['conviction_tier']} -- {state}"
        )
        lines.append(s["message"])
        lines.append("")
    return "\n".join(lines).strip()


def format_replay(snapshot: dict | None) -> str:
    if snapshot is None:
        return "No market snapshot has been taken yet -- check back shortly."
    lines = [
        f"*MARKET REPLAY* ({snapshot['computed_at']})",
        "",
        f"Regime: {(snapshot['regime'] or 'unknown').replace('_', ' ').title()}",
        (
            f"Health {snapshot['health_score']} | Trend {snapshot['trend_strength_score']} | "
            f"Risk {snapshot['risk_score']} | Confidence {snapshot['confidence_score']}"
        ),
    ]
    if snapshot["consensus"]:
        c = snapshot["consensus"]
        lines.append(
            f"Consensus: bullish {c['bullish_pct']}% / bearish {c['bearish_pct']}% / "
            f"neutral {c['neutral_pct']}% (conflict {c['conflict_pct']}%)"
        )
    if snapshot["portfolio_advice"]:
        pa = snapshot["portfolio_advice"]
        lines.append(f"Portfolio advice ({pa['symbol']}): {pa['recommendation']}")
    if snapshot["alerts"]:
        lines.append(f"Alerts since previous snapshot: {len(snapshot['alerts'])}")
    return "\n".join(lines)


def format_advice(advice: dict | None, symbol: str, timeframe_arg: str) -> str:
    if advice is None:
        return (
            f"Not enough data yet for {symbol}/{timeframe_arg} -- needs synced history "
            "(run sync_history.py), a computed Signal snapshot and a computed "
            "Probability snapshot."
        )
    probs = advice["probability"]
    lines = [
        f"*{advice['symbol']} ADVICE* ({advice['timeframe']}) -- {advice['recommendation']}",
        "",
        advice["reasoning"],
        "",
        f"Reference price: {advice['entry_reference_price']:,.2f}",
        f"ATR: {advice['atr']:.4f}" if advice["atr"] is not None else "ATR: unavailable",
        f"Probability -- up: {probs['up']}% | down: {probs['down']}% | flat: {probs['flat']}%",
    ]
    if advice["stop_loss_price"] is not None:
        lines.append("")
        lines.append(f"Stop-loss: {advice['stop_loss_price']:,.2f}")
        lines.append(f"Take-profit: {advice['take_profit_price']:,.2f}")
        lines.append(f"Risk:reward: 1:{advice['risk_reward_ratio']:.1f}")
    if advice["position_size_note"]:
        lines.append(
            f"Position size: {advice['position_size_quantity']} -- {advice['position_size_note']}"
        )
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


def format_strategy_result(result: dict | None) -> str:
    if result is None:
        return "No historical occurrences of this rule found."
    lines = [
        f"*STRATEGY: {result['target_symbol']}* ({result['timeframe']}, "
        f"{result['horizon_periods']}-period horizon)",
        "",
        f"Occurrences: {result['occurrences']}",
        f"Win rate: {result['win_rate_pct']}%",
        f"Avg return: {result['avg_return_pct']}%",
        f"Max drawdown: {result['max_drawdown_pct']}%",
        f"Profit factor: {result['profit_factor']}",
        f"Sharpe ratio: {result['sharpe_ratio']}",
    ]
    if result.get("stop_loss_pct") is not None:
        lines.append(f"Stop loss: {result['stop_loss_pct']:.2%}")
    if result.get("take_profit_pct") is not None:
        lines.append(f"Take profit: {result['take_profit_pct']:.2%}")
    if result.get("position_size_pct") is not None:
        lines.append(f"Position size: {result['position_size_pct']:.0%}")
    return "\n".join(lines)


def format_walk_forward(folds: list[dict]) -> str:
    if not folds:
        return "Not enough stored history for walk-forward testing."
    lines = ["*WALK-FORWARD TEST*", ""]
    for fold in folds:
        metrics = fold["metrics"]
        lines.append(f"Fold {fold['fold']} ({fold['start_date'][:10]} to {fold['end_date'][:10]}):")
        if metrics is None:
            lines.append("  No occurrences in this window.")
        else:
            lines.append(
                f"  {metrics['occurrences']} trades, {metrics['win_rate_pct']}% win rate, "
                f"{metrics['avg_return_pct']}% avg return"
            )
    return "\n".join(lines)


def format_monte_carlo(result: dict | None) -> str:
    if result is None:
        return "Not enough historical trades to run a Monte Carlo simulation (need at least 2)."
    return "\n".join(
        [
            f"*MONTE CARLO: {result['target_symbol']}* "
            f"({result['n_simulations']} simulations, {result['trades_per_sim']} trades each)",
            "",
            f"Total return: {result['total_return_p5_pct']}% (p5) / "
            f"{result['total_return_p50_pct']}% (p50) / {result['total_return_p95_pct']}% (p95)",
            f"Max drawdown: {result['max_drawdown_p50_pct']}% (p50) / "
            f"{result['max_drawdown_p95_pct']}% (p95)",
        ]
    )


def format_hypothesis(row) -> str:
    lines = [
        f"*HYPOTHESIS: {row.statement}*",
        "",
        f"Verdict: {row.verdict.value.upper()}",
        row.reason,
    ]
    return "\n".join(lines)


def format_hypothesis_list(rows: list) -> str:
    if not rows:
        return "No hypotheses tested yet."
    lines = ["*RECENT HYPOTHESES*", ""]
    for row in rows:
        lines.append(f"- [{row.verdict.value.upper()}] {row.statement}")
    return "\n".join(lines)


def format_ranking(row) -> str:
    if row is None:
        return "No ranking computed yet."
    lines = [f"*FACTOR RANKING vs {row.target_symbol}*", ""]
    for entry in row.rankings:
        current = entry.get("current_importance_pct")
        historical = entry.get("historical_importance_pct")
        current_str = f"{current}%" if current is not None else "n/a"
        historical_str = f"{historical}%" if historical is not None else "n/a"
        lines.append(
            f"{entry['rank']}. {entry['factor']} -- current edge {current_str}, "
            f"historical edge {historical_str}, confidence (n={entry['confidence']})"
        )
    return "\n".join(lines)


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
